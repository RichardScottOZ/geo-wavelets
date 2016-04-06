#! /usr/bin/env python3
"""
A demo script that ties some of the command line utilities together in a
pipeline

TODO: Replicate this with luigi or joblib
"""

import logging
import tables
import pickle
import numpy as np
from os import path, mkdir
from glob import glob
from subprocess import run, CalledProcessError

from sklearn.decomposition import PCA
from sklearn.preprocessing import robust_scale, Imputer

from uncoverml import validation

log = logging.getLogger(__name__)


# Settings
data_dir = path.join(path.expanduser("~"), "data/GA-cover")
proc_dir = path.join(data_dir, "processed")

target_file = "geochem_sites.shp"
target_var = "Na_ppm_i_1"
target_hdf = path.join(proc_dir, "{}_{}.hdf5"
                       .format(path.splitext(target_file)[0], target_var))
cv_file = path.join(data_dir, "soilcrossvalindices.hdf5")
feat_file = path.join(proc_dir, "features_0.hdf5")

algorithm = "randomforest"
# algorithm = "bayesreg"
whiten = False  # whiten all of the extracted features?
standardise = False  # standardise all of the extracted features?
pca_dims = 25  # if whitening, how many PCA dimensions to keep?

removedims = []


def main():

    logging.basicConfig(level=logging.INFO)

    # Make processed dir if it does not exist
    if not path.exists(proc_dir):
        mkdir(proc_dir)
        log.info("Made processed dir")

    # Make pointspec and hdf5 for targets
    cmd = ["maketargets", path.join(data_dir, target_file), target_var,
           "--outfile", target_hdf]

    if try_run_checkfile(cmd, target_hdf):
        log.info("Made targets")

    # Extract feats for training
    tifs = glob(path.join(data_dir, "*.tif"))
    if len(tifs) == 0:
        raise PipeLineFailure("No geotiffs found in {}!".format(data_dir))

    ffiles = []
    for tif in tifs:
        name = path.splitext(path.basename(tif))[0]
        cmd = ["extractfeats", tif, name, "--outputdir", proc_dir, "--chunks",
               "1", "--targets", target_hdf, "--standalone"]
        msg = "Processing {}.".format(path.basename(tif))
        ffile = path.join(proc_dir, name + "_0.hdf5")
        try_run_checkfile(cmd, ffile, msg)
        ffiles.append(ffile)

    # Compose individual image features into single feature vector
    # TODO use a script for this ----------------------------------------------
    feats = []
    for ffile in ffiles:
        with tables.open_file(ffile, mode='r') as f:
            feat = f.root.features.read()
            feats.append(feat)

    X = np.hstack(feats)
    keepind = np.ones(X.shape[1], dtype=bool)
    keepind[removedims] = False
    X = X[:, keepind]

    # Remove NaNs TODO remove NaNs properly!
    imp = Imputer(missing_values=X.min(), strategy="median")
    X = imp.fit_transform(X)

    # Int to one-hot TODO

    # Standardise features
    if standardise:
        log.info("Standartising the features.")
        X = robust_scale(X, with_centering=True, with_scaling=True)

    # Whiten the features
    if whiten:
        log.info("Whitening the features.")
        pca = PCA(n_components=pca_dims, whiten=True)
        X = pca.fit_transform(X)

    # D = X.shape[1]

    # Save whitening parameters to model spec
    # TODO

    # Save features to feature file
    with tables.open_file(feat_file, mode='w') as f:
        f.create_array("/", "features", obj=X)
    # -------------------------------------------------------------------------

    # Train the model
    cmd = ["learnmodel", "--outputdir", proc_dir, "--cvindex", cv_file, "0",
           "--algorithm", algorithm, feat_file, target_hdf]

    log.info("Training model.")
    alg_file = path.join(proc_dir, "{}.pk".format(algorithm))
    run(cmd)

    # Test the model
    # TODO this will be in the predict script ---------------------------------

    # Divide the features into cross-val folds
    with tables.open_file(cv_file, mode='r') as f:
        cv_ind = f.root.FoldIndices.read().flatten()

    Xs = X[cv_ind == 0]

    with tables.open_file(target_hdf, mode='r') as f:
        Y = f.root.targets.read()

    Ys = Y[cv_ind == 0]

    log.info("Testing model.")
    with open(alg_file, 'rb') as f:
        mod = pickle.load(f)

    if algorithm == 'bayesreg':
        EYs, Vfs, VYs = mod.predict(Xs)
    else:
        EYs = mod.predict(Xs)

    # EYs = rfr.predict(Xs)

    # -------------------------------------------------------------------------

    # Report score
    Rsquare = validation.rsquare(EYs, Ys)

    log.info("Done! R-square = {}".format(Rsquare))


class PipeLineFailure(Exception):
    pass


def combinefeats(tifs):

    pass


def try_run_checkfile(cmd, checkfile, premsg=None):

    if not path.exists(checkfile):
        if premsg:
            log.info(premsg)
        try_run(cmd)
        return True

    return False


def try_run(cmd):

    try:
        run(cmd, check=True)
    except CalledProcessError:
        log.info("\n--------------------\n")
        raise


if __name__ == "__main__":
    main()