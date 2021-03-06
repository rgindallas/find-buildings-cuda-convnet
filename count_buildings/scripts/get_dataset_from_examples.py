import h5py
import numpy as np
import os
import random
import sys
from crosscompute.libraries import script
from shapely.geometry import box

from ..libraries import satellite_image
from .get_examples_from_points import EXAMPLES_NAME


DATASET_NAME = 'dataset.h5'


def start(argv=sys.argv):
    with script.Starter(run, argv) as starter:
        starter.add_argument(
            '--examples_folder', metavar='FOLDER', required=True,
            help='extracted examples')
        starter.add_argument(
            '--maximum_dataset_size', metavar='SIZE',
            type=script.parse_size,
            help='maximum number of examples to include')
        starter.add_argument(
            '--positive_fraction', metavar='FRACTION',
            type=float,
            help='set fraction of positive to negative examples')
        starter.add_argument(
            '--excluded_pixel_bounds', metavar='MIN_X,MIN_Y,MAX_X,MAX_Y',
            type=script.parse_bounds,
            help='ignore specified bounds')
        starter.add_argument(
            '--batch_size', metavar='SIZE',
            type=script.parse_size,
            help='ensure dataset size is divisible by batch size')


def run(
        target_folder, examples_folder, maximum_dataset_size=None,
        positive_fraction=None, excluded_pixel_bounds=None, batch_size=None):
    examples_h5 = h5py.File(os.path.join(examples_folder, EXAMPLES_NAME), 'r')
    positive_indices = get_indices(
        examples_h5['positive'], maximum_dataset_size, excluded_pixel_bounds)
    negative_indices = get_indices(
        examples_h5['negative'], maximum_dataset_size, excluded_pixel_bounds)
    positive_count, negative_count = adjust_counts(
        len(positive_indices), len(negative_indices),
        maximum_dataset_size, positive_fraction, batch_size)
    dataset_h5 = get_dataset_h5(target_folder)
    save_dataset(
        dataset_h5, examples_h5,
        fit_indices(positive_indices, positive_count),
        fit_indices(negative_indices, negative_count))
    example_count = positive_count + negative_count
    return dict(
        dataset_size=script.format_size(example_count),
        positive_fraction=positive_count / float(example_count),
        positive_count=positive_count,
        negative_count=negative_count)


def get_indices(examples, maximum_dataset_size, excluded_pixel_bounds):
    eligible_indices = []
    arrays = examples['arrays']
    for index, array in enumerate(arrays):
        if array.max() == 0:
            continue
        eligible_indices.append(index)
    if not excluded_pixel_bounds:
        return eligible_indices
    included_indices = []
    pixel_centers = examples['pixel_centers'][:maximum_dataset_size]
    pixel_dimensions = arrays.shape[1:3]
    excluded_pixel_box = box(*excluded_pixel_bounds)
    for index in eligible_indices:
        pixel_center = pixel_centers[index]
        pixel_bounds = satellite_image.get_pixel_bounds_from_pixel_center(
            pixel_center, pixel_dimensions)
        pixel_box = box(*pixel_bounds)
        if pixel_box.intersects(excluded_pixel_box):
            continue
        included_indices.append(index)
    return included_indices


def adjust_counts(
        positive_count, negative_count,
        maximum_dataset_size, positive_fraction, batch_size):
    # Get new_dataset_size
    dataset_size = positive_count + negative_count
    new_dataset_size = min(
        maximum_dataset_size or dataset_size, dataset_size)
    # Round up
    if new_dataset_size % batch_size:
        new_dataset_size = (new_dataset_size / batch_size + 1) * batch_size
    # Get positive_fraction
    if positive_fraction is None:
        positive_fraction = positive_count / float(dataset_size)
    else:
        positive_fraction = min(1, positive_fraction)
    new_positive_count = int(round(positive_fraction * new_dataset_size))
    new_negative_count = new_dataset_size - new_positive_count
    return new_positive_count, new_negative_count


def get_dataset_h5(target_folder):
    return h5py.File(os.path.join(target_folder, DATASET_NAME), 'w')


def save_dataset(dataset_h5, examples_h5, positive_indices, negative_indices):
    dataset_size = len(positive_indices) + len(negative_indices)
    positive_packs = [(_, True) for _ in positive_indices]
    negative_packs = [(_, False) for _ in negative_indices]
    dataset_packs = positive_packs + negative_packs
    random.shuffle(dataset_packs)
    positive_arrays = examples_h5['positive']['arrays']
    positive_pixel_centers = examples_h5['positive']['pixel_centers']
    arrays = dataset_h5.create_dataset(
        'arrays', shape=(dataset_size,) + positive_arrays.shape[1:],
        dtype=positive_arrays.dtype)
    pixel_centers = dataset_h5.create_dataset(
        'pixel_centers', shape=(dataset_size, 2),
        dtype=positive_pixel_centers.dtype)
    for key, value in positive_pixel_centers.attrs.iteritems():
        pixel_centers.attrs[key] = value
    labels = dataset_h5.create_dataset(
        'labels', shape=(dataset_size,), dtype=bool)
    index = 0
    for index, (inner_index, label) in enumerate(dataset_packs):
        if index % 1000 == 0:
            print '%s / %s' % (index, dataset_size - 1)
        inner_examples = examples_h5['positive' if label else 'negative']
        arrays[index, :, :, :] = inner_examples['arrays'][inner_index]
        labels[index] = label
        pixel_centers[index, :] = inner_examples['pixel_centers'][inner_index]
    print '%s / %s' % (index, dataset_size - 1)


def fit_indices(indices, count):
    index_count = len(indices)
    if index_count >= count:
        return indices[:count]
    return np.tile(indices, 1 + count / index_count)[:count]
