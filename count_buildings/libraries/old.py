import numpy as np
import random
from functools import partial
from itertools import product
from matplotlib import pyplot as plt
from osgeo import gdal, osr
from shapely.geometry import box

from . import calculator


class Calibration(object):

    def __init__(self, calibration_pack):
        self._calibration_pack = calibration_pack

    def to_xy(self, (pixel_x, pixel_y)):
        'Get geographic coordinates given pixel coordinates'
        g0, g1, g2, g3, g4, g5 = self._calibration_pack
        x = g0 + pixel_x * g1 + pixel_y * g2
        y = g3 + pixel_x * g4 + pixel_y * g5
        return np.array([x, y])

    def to_pixel_xy(self, (x, y)):
        'Get pixel coordinates given geographic coordinates'
        g0, g1, g2, g3, g4, g5 = self._calibration_pack
        pixel_x = (-g0 * g5 + g2 * g3 - g2 * y + g5 * x) / (g1 * g5 - g2 * g4)
        pixel_y = (-g1 * (g3 - y) + g4 * (g0 - x)) / (g1 * g5 - g2 * g4)
        return np.array([
            calculator.round_integer(pixel_x),
            calculator.round_integer(pixel_y)])

    def to_dimensions(self, (pixel_width, pixel_height)):
        'Get geographic dimensions given pixel dimensions'
        g0, g1, g2, g3, g4, g5 = self._calibration_pack
        return np.array([
            abs(pixel_width * g1),
            abs(pixel_height * g5)])

    def to_pixel_dimensions(self, (width, height)):
        'Get pixel dimensions given geographic dimensions'
        g0, g1, g2, g3, g4, g5 = self._calibration_pack
        return np.array([
            calculator.round_integer(width / float(g1)),
            calculator.round_integer(height / float(g5))])


class SatelliteImage(Calibration):

    def __init__(self, image_path):
        image = gdal.Open(image_path)
        self._image = image
        self._vmin, self._vmax = _get_extreme_values(image)
        super(SatelliteImage, self).__init__(image.GetGeoTransform())
        self.pixel_dimensions = image.RasterXSize, image.RasterYSize
        self.pixel_dtype = np.min_scalar_type(max(self.pixel_dimensions))
        self.band_count = image.RasterCount
        self.spatial_reference = osr.SpatialReference()
        self.spatial_reference.ImportFromWkt(image.GetProjectionRef())
        self.proj4 = self.spatial_reference.ExportToProj4()
        self.array_dtype = self.get_array_from_pixel_frame(
            ((0, 0), (0, 0))).dtype
        self.save_image = partial(plt.imsave, vmin=self._vmin, vmax=self._vmax)

    def save_image_from_pixel_frame(self, target_path, pixel_frame):
        array = self.get_array_from_pixel_frame(pixel_frame)
        self.save_image(target_path, array[:, :, :3])
        return array

    def get_array_from_pixel_frame(self, pixel_frame):
        pixel_upper_left, pixel_dimensions = self._clip_pixel_frame(
            pixel_frame)
        pixel_x, pixel_y = pixel_upper_left
        array = self._image.ReadAsArray(pixel_x, pixel_y, *pixel_dimensions)
        return np.rollaxis(array, 0, start=3)

    def _clip_pixel_frame(self, (pixel_upper_left, pixel_dimensions)):
        pixel_upper_left = np.array(pixel_upper_left)
        pixel_x1, pixel_y1 = self._clip_pixel_xy(
            pixel_upper_left)
        pixel_x2, pixel_y2 = self._clip_pixel_xy(
            pixel_upper_left + pixel_dimensions)
        return (pixel_x1, pixel_y1), (pixel_x2 - pixel_x1, pixel_y2 - pixel_y1)

    def _clip_pixel_xy(self, pixel_xy):
        return np.maximum((0, 0), np.minimum(self.pixel_dimensions, pixel_xy))


class ImageScope(SatelliteImage):

    def __init__(self, image_path, scope_dimensions):
        super(ImageScope, self).__init__(image_path)
        self.scope_dimensions = scope_dimensions
        self.scope_pixel_dimensions = self.to_pixel_dimensions(
            scope_dimensions)

    def yield_pixel_upper_left(
            self, interval_pixel_dimensions, targeted_pixel_bounds=None,
            targeted_indices=None):
        image_pixel_width, image_pixel_height = self.pixel_dimensions
        interval_pixel_width, interval_pixel_height = interval_pixel_dimensions
        targeted_pixel_box = box(
            *targeted_pixel_bounds) if targeted_pixel_bounds else None
        pixel_x_iter = xrange(0, image_pixel_width, interval_pixel_width)
        pixel_y_iter = xrange(0, image_pixel_height, interval_pixel_height)

        for pixel_index, pixel_upper_left in enumerate(product(
                pixel_x_iter, pixel_y_iter)):
            if targeted_indices and pixel_index not in targeted_indices:
                continue
            if targeted_pixel_box:
                pixel_bounds = self.get_pixel_bounds_from_pixel_upper_left(
                    pixel_upper_left)
                pixel_box = box(*pixel_bounds)
                if not pixel_box.intersects(targeted_pixel_box):
                    continue
            yield pixel_index, pixel_upper_left

    def save_image_from_center(self, target_path, center):
        pixel_center = self.to_pixel_xy(center)
        return self.save_image_from_pixel_center(target_path, pixel_center)

    def save_image_from_pixel_center(self, target_path, pixel_center):
        pixel_frame = self.get_pixel_frame_from_pixel_center(pixel_center)
        return self.save_image_from_pixel_frame(target_path, pixel_frame)

    def save_image_from_upper_left(self, target_path, upper_left):
        pixel_upper_left = self.to_pixel_xy(upper_left)
        return self.save_image_from_pixel_upper_left(
            target_path, pixel_upper_left)

    def save_image_from_pixel_upper_left(self, target_path, pixel_upper_left):
        pixel_frame = pixel_upper_left, self.scope_pixel_dimensions
        return self.save_image_from_pixel_frame(target_path, pixel_frame)

    def get_array_from_center(self, center):
        pixel_center = self.to_pixel_xy(center)
        return self.get_array_from_pixel_center(pixel_center)

    def get_array_from_pixel_center(self, pixel_center):
        pixel_frame = self.get_pixel_frame_from_pixel_center(pixel_center)
        return self.get_array_from_pixel_frame(pixel_frame)

    def get_array_from_upper_left(self, upper_left):
        pixel_upper_left = self.to_pixel_xy(upper_left)
        return self.get_array_from_pixel_upper_left(pixel_upper_left)

    def get_array_from_pixel_upper_left(self, pixel_upper_left):
        pixel_frame = pixel_upper_left, self.scope_pixel_dimensions
        return self.get_array_from_pixel_frame(pixel_frame)

    def get_pixel_bounds_from_pixel_center(self, pixel_center):
        return get_pixel_bounds_from_pixel_center(
            pixel_center, self.scope_pixel_dimensions)

    def get_pixel_bounds_from_pixel_upper_left(self, pixel_upper_left):
        return get_pixel_bounds_from_pixel_upper_left(
            pixel_upper_left, self.scope_pixel_dimensions)

    def get_pixel_frame_from_pixel_center(self, pixel_center):
        return get_pixel_frame_from_pixel_center(
            pixel_center, self.scope_pixel_dimensions)

    def get_random_pixel_center(self):
        minimum_pixel_center = get_pixel_center_from_pixel_frame((
            (0, 0),
            self.scope_pixel_dimensions))
        maximum_pixel_center = get_pixel_center_from_pixel_frame((
            self.pixel_dimensions - self.scope_pixel_dimensions,
            self.scope_pixel_dimensions))
        return np.array([
            random.randint(minimum_pixel_center[0], maximum_pixel_center[0]),
            random.randint(minimum_pixel_center[1], maximum_pixel_center[1]),
        ])


def _get_extreme_values(image):
    'Get minimum and maximum pixel values'
    band_count = image.RasterCount
    bands = [image.GetRasterBand(x + 1) for x in xrange(band_count)]
    minimums = [x.GetMinimum() for x in bands]
    maximums = [x.GetMaximum() for x in bands]
    values = [x for x in minimums + maximums if x is not None]
    return min(values), max(values)


def get_pixel_bounds_from_pixel_center(
        pixel_center, pixel_dimensions):
    pixel_frame = get_pixel_frame_from_pixel_center(
        pixel_center, pixel_dimensions)
    pixel_upper_left, pixel_dimensions = pixel_frame
    return get_pixel_bounds_from_pixel_upper_left(
        pixel_upper_left, pixel_dimensions)


def get_pixel_bounds_from_pixel_upper_left(
        pixel_upper_left, pixel_dimensions):
    pixel_lower_right = pixel_upper_left + pixel_dimensions
    return list(pixel_upper_left) + list(pixel_lower_right)


def get_pixel_frame_from_pixel_center(pixel_center, pixel_dimensions):
    pixel_upper_left = pixel_center - np.array(pixel_dimensions) / 2
    return pixel_upper_left, pixel_dimensions


def get_pixel_center_from_pixel_frame(pixel_frame):
    pixel_upper_left, pixel_dimensions = pixel_frame
    return pixel_upper_left + np.array(pixel_dimensions) / 2
