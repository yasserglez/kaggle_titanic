import os
import sys
import pprint
import logging
import multiprocessing as mp
from collections import defaultdict
from datetime import datetime

import numpy as np
from numpy.random import RandomState
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
import xgboost as xgb
import joblib

import common
import base
import preprocessing


logger = logging.getLogger(__name__)


class XGB(base.BaseModel):

    def main(self):
        t_start = datetime.now()
        logger.info(' {} / {} '.format(self.name, self.random_seed).center(62, '='))
        logger.info('Hyperparameters:\n{}'.format(pprint.pformat(self.params)))
        if os.path.isfile(os.path.join(self.output_dir, 'test.csv')):
            logger.info('Output already exists - skipping')

        # Initialize the random number generator
        self.random_state = RandomState(self.random_seed)
        np.random.seed(int.from_bytes(self.random_state.bytes(4), byteorder=sys.byteorder))

        preprocessed_data = preprocessing.load(self.params)
        vectorizer = self.build_vectorizer(preprocessed_data)

        train_df = common.load_data('train')
        train_df['comment_text'] = train_df['id'].map(preprocessed_data)
        test_df = common.load_data('test')
        test_df['comment_text'] = test_df['id'].map(preprocessed_data)

        folds = common.stratified_kfold(train_df, random_seed=self.random_seed)
        for fold_num, train_ids, val_ids in folds:
            logger.info(f'Fold #{fold_num}')

            fold_train_df = train_df[train_df['id'].isin(train_ids)]
            fold_val_df = train_df[train_df['id'].isin(val_ids)]
            models = self.train(fold_num, vectorizer, fold_train_df, fold_val_df)

            logger.info('Generating the out-of-fold predictions')
            path = os.path.join(self.output_dir, f'fold{fold_num}_validation.csv')
            self.predict(models, vectorizer, fold_val_df, path)

            logger.info('Generating the test predictions')
            path = os.path.join(self.output_dir, f'fold{fold_num}_test.csv')
            self.predict(models, vectorizer, test_df, path)

        logger.info('Combining the out-of-fold predictions')
        df_parts = []
        for fold_num in range(1, 11):
            path = os.path.join(self.output_dir, f'fold{fold_num}_validation.csv')
            df_part = pd.read_csv(path, usecols=['id'] + common.LABELS)
            df_parts.append(df_part)
        train_pred = pd.concat(df_parts)
        path = os.path.join(self.output_dir, 'train.csv')
        train_pred.to_csv(path, index=False)

        logger.info('Averaging the test predictions')
        df_parts = []
        for fold_num in range(1, 11):
            path = os.path.join(self.output_dir, f'fold{fold_num}_test.csv')
            df_part = pd.read_csv(path, usecols=['id'] + common.LABELS)
            df_parts.append(df_part)
        test_pred = pd.concat(df_parts).groupby('id', as_index=False).mean()
        path = os.path.join(self.output_dir, 'test.csv')
        test_pred.to_csv(path, index=False)

        logger.info('Total elapsed time - {}'.format(datetime.now() - t_start))

    def train(self, fold_num, vectorizer, train_df, val_df):
        X_train = vectorizer.transform(train_df['comment_text'])
        X_val = vectorizer.transform(val_df['comment_text'])

        models = {}
        for label in common.LABELS:
            logger.info('Training the %s model', label)
            y_train, y_val = train_df[label].values, val_df[label].values

            model = xgb.XGBClassifier(
                n_estimators=10000,  # determined by early stopping
                objective='binary:logistic',
                max_depth=self.params['max_depth'],
                min_child_weight=self.params['min_child_weight'],
                subsample=self.params['subsample'],
                colsample_bytree=self.params['colsample_bytree'],
                learning_rate=self.params['learning_rate'],
                random_state=self.random_seed,
                n_jobs=mp.cpu_count())

            model.fit(X_train, y_train,
                      eval_set=[(X_val, y_val)], eval_metric='auc',
                      early_stopping_rounds=self.params['patience'])

            models[label] = model

        path = os.path.join(self.output_dir, f'fold{fold_num}.pickle')
        joblib.dump((vectorizer, models), path)
        return models

    def predict(self, models, vectorizer, df, output_path):
        X = vectorizer.transform(df['comment_text'])
        output = defaultdict(list)
        for label in common.LABELS:
            model = models[label]
            yhat = model.predict_proba(X, ntree_limit=model.best_ntree_limit)[:, 1]
            output[label].extend(yhat)
        predictions = pd.DataFrame.from_dict(output)
        predictions = predictions[common.LABELS]
        predictions.insert(0, 'id', df['id'].values)
        predictions.to_csv(output_path, index=False)

    def build_vectorizer(self, preprocessed_data):
        logger.info('Learning the vocabulary')
        vectorizer = TfidfVectorizer(min_df=self.params['min_df'])
        vectorizer.fit(preprocessed_data.values())
        logger.info('The vocabulary has %s words (%s ignored as stopwords)', 
                    len(vectorizer.vocabulary_), len(vectorizer.stop_words_))
        return vectorizer


if __name__ == '__main__':
    params = {
        'vocab_size': 300000,
        'max_len': 1000,
        'min_df': 5,
        'max_depth': 6,
        'min_child_weight': 1,
        'subsample': 0.4,
        'colsample_bytree': 0.5,
        'learning_rate': 0.1,
        'patience': 50,
    }
    model = XGB(params, random_seed=base.RANDOM_SEED)
    model.main()
