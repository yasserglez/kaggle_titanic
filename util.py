import os
import sys

from sklearn.base import BaseEstimator, TransformerMixin


def get_random_seed(num_bytes=4):
    seed = int.from_bytes(os.urandom(num_bytes), sys.byteorder)
    return seed


class ModelImputer(BaseEstimator, TransformerMixin):

    def __init__(self, model, y_column, X_columns=None):
        self.model = model
        self.y_column = y_column
        self.X_columns = X_columns

    def _get_X_columns(self, X):
        return (self.X_columns if self.X_columns else
                [i for i in range(X.shape[1]) if i != self.y_column])

    def fit(self, X, y=None):
        complete = X[:, self.y_column] != -1
        X_complete = X[complete, :]
        X_columns = self._get_X_columns(X)
        self.model.fit(X_complete[:, X_columns], X_complete[:, self.y_column])
        return self

    def transform(self, X):
        missing = X[:, self.y_column] == -1
        if missing.any():
            X_missing = X[missing, :]
            X_columns = self._get_X_columns(X)
            y_imputed = self.model.predict(X_missing[:, X_columns])
            X[missing, self.y_column] = y_imputed
        return X
