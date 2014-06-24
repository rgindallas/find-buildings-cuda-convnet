CLASSIFIER_NAMES="
uganda-20140619-0812
"
CLASSIFIER_NAMES="
uganda-20140622-0131
uganda-20140623-141751
uganda-20140623-173736
"
export EXPERIMENT_NAME=`basename $(dirname $(dirname $(pwd)/$0))`
export IMAGE_NAME=uganda1
export IMAGE_PATH=~/Links/satellite-images/$IMAGE_NAME
export POINTS_PATH=~/Links/building-locations/$IMAGE_NAME
export EXAMPLE_DIMENSIONS=19x19
export OVERLAP_DIMENSIONS=9.5x9.5
export ARRAY_SHAPE=32,32,3
export ACTUAL_RADIUS=9.5
export RANDOM_SEED=crosscompute
export BATCH_SIZE=5k
export TILE_DIMENSIONS=1000,1000
# bash prepare_scan.sh
for CLASSIFIER_NAME in $CLASSIFIER_NAMES; do
    export CLASSIFIER_NAME
    export CLASSIFIER_PATH=~/Storage/building-classifiers/$CLASSIFIER_NAME
    bash scan.sh
done
