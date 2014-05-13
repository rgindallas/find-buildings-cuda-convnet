import h5py
import os
import sys
from crosscompute.libraries import script

from .get_tiles_from_image import save_image_dimensions
from ..libraries import satellite_image


ARRAYS_NAME = 'arrays.h5'


def start(argv=sys.argv):
    with script.Starter(run, argv) as starter:
        starter.add_argument(
            '--image_path', metavar='PATH', required=True,
            help='satellite image')
        starter.add_argument(
            '--tile_dimensions', metavar='WIDTH,HEIGHT',
            type=script.parse_dimensions,
            help='dimensions of extracted tile in geographic units')
        starter.add_argument(
            '--overlap_dimensions', metavar='WIDTH,HEIGHT', default=(0, 0),
            type=script.parse_dimensions,
            help='dimensions of tile overlap in geographic units')
        starter.add_argument(
            '--included_pixel_bounds', metavar='MIN_X,MIN_Y,MAX_X,MAX_Y',
            type=script.parse_bounds,
            help='target specified bounds')


def run(
        target_folder, image_path,
        tile_dimensions, overlap_dimensions, included_pixel_bounds):
    if tile_dimensions is None and included_pixel_bounds is None:
        return save_image_dimensions(image_path)
    elif tile_dimensions is None:
        return save_pixel_bounds(
            target_folder, image_path, included_pixel_bounds)
    return save_arrays(
        target_folder, image_path,
        tile_dimensions, overlap_dimensions, included_pixel_bounds)


def save_pixel_bounds(
        target_folder, image_path, included_pixel_bounds):
    pixel_frame = [
        pixel_upper_left, pixel_dimensions
    ] = satellite_image.get_pixel_frame_from_pixel_bounds(
        included_pixel_bounds)
    image = satellite_image.SatelliteImage(image_path)

    tile_dimensions = image.to_dimensions(pixel_dimensions)
    arrays, pixel_upper_lefts = get_target_pack(
        target_folder, image_path, tile_dimensions, tile_count=1)
    arrays[0, :, :, :] = image.get_array_from_pixel_frame(pixel_frame)
    pixel_upper_lefts[0, :] = pixel_upper_left
    return dict(
        tile_dimensions=tile_dimensions,
        tile_pixel_dimensions=pixel_dimensions)


def save_arrays(
        target_folder, image_path,
        tile_dimensions, overlap_dimensions,
        included_pixel_bounds):
    image_scope = satellite_image.ImageScope(image_path, tile_dimensions)
    tile_packs = list(image_scope.yield_tile_pack(
        overlap_dimensions, included_pixel_bounds))
    array_count = len(tile_packs)
    arrays, pixel_upper_lefts = get_target_pack(
        target_folder, image_path, tile_dimensions, array_count)
    for array_index, (tile_index, pixel_upper_left) in enumerate(tile_packs):
        array = image_scope.get_array_from_pixel_upper_left(pixel_upper_left)
        arrays[array_index, :, :, :] = array
        pixel_upper_lefts[array_index, :] = pixel_upper_left
    return dict(
        tile_pixel_dimensions=image_scope.scope_pixel_dimensions,
        overlap_pixel_dimensions=image_scope.to_pixel_dimensions(
            overlap_dimensions),
        array_count=array_count)


def get_target_pack(target_folder, image_path, tile_dimensions, tile_count):
    image = satellite_image.SatelliteImage(image_path)
    tile_pixel_dimensions = image.to_pixel_dimensions(tile_dimensions)
    tile_pixel_width, tile_pixel_height = tile_pixel_dimensions
    arrays_h5 = get_arrays_h5(target_folder)
    arrays = arrays_h5.create_dataset(
        'arrays', shape=(
            tile_count, tile_pixel_height, tile_pixel_width,
            image.band_count), dtype=image.array_dtype)
    pixel_upper_lefts = arrays_h5.create_dataset(
        'pixel_upper_lefts', shape=(
            tile_count, 2), dtype=image.pixel_dtype)
    pixel_upper_lefts.attrs['calibration_pack'] = image.calibration_pack
    pixel_upper_lefts.attrs['proj4'] = image.proj4
    arrays_h5.create_dataset('labels', shape=(0,), dtype=bool)
    return arrays, pixel_upper_lefts


def get_arrays_h5(target_folder):
    return h5py.File(os.path.join(target_folder, ARRAYS_NAME), 'w')