import numpy as np
import random
import utm
from geometryIO import get_transformPoint
from invisibleroads_macros.calculator import round_number
from os.path import realpath
from osgeo import gdal, osr
from scipy.misc import toimage
from skimage.exposure import rescale_intensity


class ProjectedCalibration(object):

    def __init__(self, calibration_pack):
        self.calibration_pack = tuple(calibration_pack)

    def _become(self, c):
        self.calibration_pack = c.calibration_pack

    def _to_projected_width(self, pixel_width):
        g0, g1, g2, g3, g4, g5 = self.calibration_pack
        return abs(pixel_width * g1)

    def _to_pixel_width(self, projected_width):
        g0, g1, g2, g3, g4, g5 = self.calibration_pack
        return round_number(projected_width / float(g1))

    def _to_projected_height(self, pixel_height):
        g0, g1, g2, g3, g4, g5 = self.calibration_pack
        return abs(pixel_height * g5)

    def _to_pixel_height(self, projected_height):
        g0, g1, g2, g3, g4, g5 = self.calibration_pack
        return round_number(projected_height / float(g5))

    def to_projected_xy(self, (pixel_x, pixel_y)):
        'Get projected coordinates given pixel coordinates'
        g0, g1, g2, g3, g4, g5 = self.calibration_pack
        projected_x = g0 + pixel_x * g1 + pixel_y * g2
        projected_y = g3 + pixel_x * g4 + pixel_y * g5
        return np.array([projected_x, projected_y])

    def to_pixel_xy(self, (projected_x, projected_y)):
        'Get pixel coordinates given projected coordinates'
        g0, g1, g2, g3, g4, g5 = self.calibration_pack
        k = float(g1 * g5 - g2 * g4)
        x = -g0 * g5 + g2 * g3 - g2 * projected_y + g5 * projected_x
        y = -g1 * (g3 - projected_y) + g4 * (g0 - projected_x)
        return np.array([round_number(x / k), round_number(y / k)])


class MetricCalibration(ProjectedCalibration):

    def __init__(self, calibration_pack, proj4):
        super(MetricCalibration, self).__init__(calibration_pack)
        self.proj4 = proj4
        self._metric_proj4 = self._get_metric_proj4()
        self._in_metric_projection = self.proj4 == self._metric_proj4
        self._transform_to_metric_xy = get_transformPoint(
            self.proj4, self._metric_proj4)
        self._transform_to_projected_xy = get_transformPoint(
            self._metric_proj4, self.proj4)
        self._metric_xy1 = self._to_metric_xy((0, 0))

    def _become(self, c):
        super(MetricCalibration, self)._become(c)
        self.proj4 = c.proj4
        self._metric_proj4 = c._metric_proj4
        self._in_metric_projection = c._in_metric_projection
        self._transform_to_metric_xy = c._transform_to_metric_xy
        self._transform_to_projected_xy = c._transform_to_projected_xy
        self._metric_xy1 = c._to_metric_xy

    def _get_metric_proj4(self):
        if '+proj=utm' in self.proj4:
            return self.proj4
        to_ll = get_transformPoint(
            self.proj4, '+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs')
        longitude, latitude = to_ll(*self.to_projected_xy((0, 0)))
        zone_number = utm.conversion.latlon_to_zone_number(latitude, longitude)
        zone_letter = utm.conversion.latitude_to_zone_letter(latitude)
        return '+proj=utm +zone=%s%s +ellps=WGS84 +units=m +no_defs' % (
            zone_number, ' +south' if zone_letter < 'N' else '')

    def _to_metric_xy(self, (pixel_x, pixel_y)):
        'Get metric coordinates given pixel coordinates'
        projected_xy = self.to_projected_xy((pixel_x, pixel_y))
        return np.array(self._transform_to_metric_xy(*projected_xy))

    def _to_pixel_xy(self, (metric_x, metric_y)):
        'Get pixel coordinates given metric coordinates'
        projected_xy = self._transform_to_projected_xy(metric_x, metric_y)
        return self.to_pixel_xy(projected_xy)

    def to_metric_dimensions(self, (pixel_width, pixel_height)):
        'Get metric dimensions given pixel dimensions'
        if self._in_metric_projection:
            metric_width = self._to_projected_width(pixel_width)
            metric_height = self._to_projected_height(pixel_height)
        else:
            metric_xy2 = self._to_metric_xy((pixel_width, pixel_height))
            metric_width, metric_height = abs(metric_xy2 - self._metric_xy1)
        return np.array([metric_width, metric_height])

    def to_pixel_dimensions(self, (metric_width, metric_height)):
        'Get pixel dimensions given metric dimensions'
        if self._in_metric_projection:
            pixel_width = self._to_pixel_width(metric_width)
            pixel_height = self._to_pixel_height(metric_height)
        else:
            metric_xy2 = self._metric_xy1 + (metric_width, metric_height)
            pixel_width, pixel_height = abs(self._to_pixel_xy(metric_xy2))
        return np.array([pixel_width, pixel_height])


class SatelliteImage(MetricCalibration):

    def __init__(self, image_path):
        self.path = realpath(image_path)
        self._image = image = gdal.Open(self.path)
        super(SatelliteImage, self).__init__(
            calibration_pack=image.GetGeoTransform(), proj4=_get_proj4(image))
        self.pixel_dimensions = np.array((
            image.RasterXSize, image.RasterYSize))
        self.pixel_coordinate_dtype = np.min_scalar_type(
            max(self.pixel_dimensions))
        self.band_count = image.RasterCount
        self.array_dtype = _get_array_dtype(image)
        self.null_values = [image.GetRasterBand(
            x + 1).GetNoDataValue() for x in xrange(self.band_count)]

    def _become(self, i):
        self._image = i._image
        super(SatelliteImage, self)._become(i)
        self.pixel_dimensions = i.pixel_dimensions
        self.pixel_coordinate_dtype = i.pixel_coordinate_dtype
        self.band_count = i.band_count
        self.array_dtype = i.array_dtype
        self.null_values = i.null_values
        self.path = i.path

    @property
    def band_extremes(self):
        try:
            return self._band_extremes
        except AttributeError:
            pass
        self._band_extremes = []
        for band_number in xrange(1, self.band_count + 1):
            band = self._image.GetRasterBand(band_number)
            band_minimum, band_maximum = band.GetMinimum(), band.GetMaximum()
            if band_minimum is None or band_maximum is None:
                band_minimum, band_maximum = band.ComputeRasterMinMax()
            self._band_extremes.append((band_minimum, band_maximum))
        return self._band_extremes

    def get_array_from_pixel_frame(
            self, (pixel_upper_left, pixel_dimensions), fill_value=0):
        pixel_x, pixel_y = pixel_upper_left
        pixel_width, pixel_height = pixel_dimensions
        try:
            array = self._image.ReadAsArray(
                round_number(pixel_x),
                round_number(pixel_y),
                round_number(pixel_width),
                round_number(pixel_height))
        except ValueError:
            raise ValueError('Pixel frame exceeds image bounds')
        if self.band_count > 1:
            array = np.rollaxis(array, 0, start=3)
        if len(set(self.null_values)) == 1:
            null_value = self.null_values[0]
            if null_value is not None:
                array[array == null_value] = fill_value
        else:
            for band_index in xrange(self.band_count):
                null_value = self.null_values[band_index]
                if null_value is None:
                    continue
                band_array = array[:, :, band_index]
                band_array[band_array == null_value] = fill_value
        return array

    def render_array_from_pixel_frame(
            self, target_path, (pixel_upper_left, pixel_dimensions)):
        array = self.get_array_from_pixel_frame((
            pixel_upper_left, pixel_dimensions))
        return render_array(target_path, array)


class PixelScope(SatelliteImage):

    def __init__(
            self, image, tile_pixel_dimensions,
            overlap_pixel_dimensions=(0, 0)):
        self._become(image)
        self.tile_pixel_dimensions = np.array(tile_pixel_dimensions)
        self.overlap_pixel_dimensions = overlap_pixel_dimensions
        self.interval_pixel_dimensions = (
            self.tile_pixel_dimensions - overlap_pixel_dimensions)
        self.column_count = _chop(
            self.pixel_dimensions[0],
            self.tile_pixel_dimensions[0],
            self.interval_pixel_dimensions[0])
        self.row_count = _chop(
            self.pixel_dimensions[1],
            self.tile_pixel_dimensions[1],
            self.interval_pixel_dimensions[1])
        self.tile_count = self.column_count * self.row_count

    def get_array_from_pixel_center(self, pixel_center):
        pixel_frame = self.get_pixel_frame_from_pixel_center(pixel_center)
        return self.get_array_from_pixel_frame(pixel_frame)

    def get_array_from_pixel_upper_left(self, pixel_upper_left):
        pixel_frame = pixel_upper_left, self.tile_pixel_dimensions
        return self.get_array_from_pixel_frame(pixel_frame)

    def get_pixel_bounds_from_pixel_center(self, pixel_center):
        return get_pixel_bounds_from_pixel_center(
            pixel_center, self.tile_pixel_dimensions)

    def get_pixel_bounds_from_pixel_upper_left(self, pixel_upper_left):
        return get_pixel_bounds_from_pixel_upper_left(
            pixel_upper_left, self.tile_pixel_dimensions)

    def get_pixel_frame_from_tile_coordinates(self, (tile_column, tile_row)):
        pixel_upper_left = np.array(
            self.interval_pixel_dimensions) * (tile_column, tile_row)
        return pixel_upper_left, self.tile_pixel_dimensions

    def get_pixel_frame_from_tile_index(self, tile_index):
        tile_column = tile_index % self.column_count
        tile_row = tile_index / self.column_count
        return self.get_pixel_frame_from_tile_coordinates((
            tile_column, tile_row))

    def get_pixel_frame_from_pixel_center(self, pixel_center):
        return get_pixel_frame_from_pixel_center(
            pixel_center, self.tile_pixel_dimensions)

    def get_random_pixel_center(self):
        x1, y1 = self.minimum_pixel_center
        x2, y2 = self.maximum_pixel_center
        return np.array([
            random.randint(x1, x2),
            random.randint(y1, y2)])

    def is_pixel_center(self, pixel_center):
        x, y = pixel_center
        min_x, min_y = self.minimum_pixel_center
        max_x, max_y = self.maximum_pixel_center
        is_x = min_x <= x and x <= max_x
        is_y = min_y <= y and y <= max_y
        return is_x and is_y

    def is_pixel_upper_left(self, pixel_upper_left):
        x, y = pixel_upper_left
        min_x, min_y = self.minimum_pixel_upper_left
        max_x, max_y = self.maximum_pixel_upper_left
        is_x = min_x <= x and x <= max_x
        is_y = min_y <= y and y <= max_y
        return is_x and is_y

    @property
    def maximum_pixel_center(self):
        'Get maximum pixel_center that will return full array'
        return get_pixel_center_from_pixel_frame((
            self.maximum_pixel_upper_left, self.tile_pixel_dimensions))

    @property
    def maximum_pixel_upper_left(self):
        'Get maximum pixel_upper_left that will return full array'
        pixel_x, pixel_y = self.pixel_dimensions - self.tile_pixel_dimensions
        return max(0, pixel_x), max(0, pixel_y)

    @property
    def minimum_pixel_center(self):
        return get_pixel_center_from_pixel_frame((
            self.minimum_pixel_upper_left, self.tile_pixel_dimensions))

    @property
    def minimum_pixel_upper_left(self):
        return 0, 0

    def render_array_from_pixel_center(self, target_path, pixel_center):
        pixel_frame = self.get_pixel_frame_from_pixel_center(pixel_center)
        return self.render_array_from_pixel_frame(target_path, pixel_frame)

    def render_array_from_pixel_upper_left(
            self, target_path, pixel_upper_left):
        pixel_frame = pixel_upper_left, self.tile_pixel_dimensions
        return self.render_array_from_pixel_frame(target_path, pixel_frame)


class MetricScope(PixelScope):

    def __init__(
            self, image, tile_metric_dimensions,
            overlap_metric_dimensions=(0, 0)):
        tile_pixel_dimensions = image.to_pixel_dimensions(
            tile_metric_dimensions)
        overlap_pixel_dimensions = image.to_pixel_dimensions(
            overlap_metric_dimensions)
        super(MetricScope, self).__init__(
            image, tile_pixel_dimensions, overlap_pixel_dimensions)
        self.tile_metric_dimensions = tile_metric_dimensions
        self.overlap_metric_dimensions = overlap_metric_dimensions

    def get_array_from_projected_center(self, projected_center):
        pixel_center = self.to_pixel_xy(projected_center)
        return self.get_array_from_pixel_center(pixel_center)

    def get_array_from_projected_upper_left(self, projected_upper_left):
        pixel_upper_left = self.to_pixel_xy(projected_upper_left)
        return self.get_array_from_pixel_upper_left(pixel_upper_left)

    def render_array_from_projected_center(
            self, target_path, projected_center):
        pixel_center = self.to_pixel_xy(projected_center)
        return self.render_array_from_pixel_center(target_path, pixel_center)

    def render_array_from_projected_upper_left(
            self, target_path, projected_upper_left):
        pixel_upper_left = self.to_pixel_xy(projected_upper_left)
        return self.render_array_from_pixel_upper_left(
            target_path, pixel_upper_left)


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


def get_pixel_frame_from_pixel_bounds(pixel_bounds):
    minimum_x, minimum_y, maximum_x, maximum_y = pixel_bounds
    pixel_upper_left = minimum_x, minimum_y
    tile_pixel_dimensions = np.array([
        (maximum_x - minimum_x),
        (maximum_y - minimum_y)])
    return pixel_upper_left, tile_pixel_dimensions


def get_pixel_frame_from_pixel_center(pixel_center, pixel_dimensions):
    pixel_upper_left = pixel_center - np.array(pixel_dimensions) / 2
    return pixel_upper_left, pixel_dimensions


def get_pixel_center_from_pixel_frame((pixel_upper_left, pixel_dimensions)):
    return pixel_upper_left + np.array(pixel_dimensions) / 2


def get_dtype_bounds(dtype):
    iinfo = np.iinfo(dtype)
    return iinfo.min, iinfo.max


def render_array(target_path, array):
    render_enhanced_array(target_path, enhance_array(array))
    return array


def render_enhanced_array(target_path, enhanced_array):
    toimage(enhanced_array).save(target_path)
    return enhanced_array


def enhance_band_array_with_contrast_stretching(band_array):
    source_min, source_max = band_array.min(), band_array.max()
    try:
        target_min, target_max = np.percentile(band_array[
            (source_min < band_array) & (band_array < source_max)
        ], (2, 98))
    except IndexError:
        return np.zeros(band_array.shape)
    return rescale_intensity(band_array, in_range=(target_min, target_max))


def enhance_array(
        array, enhance_band_array=enhance_band_array_with_contrast_stretching,
        for_visualization=True):
    if for_visualization:
        array = array[:, :, :3]
    enhanced_array = np.zeros(array.shape)
    band_count = array.shape[-1]
    for band_index in xrange(band_count):
        enhanced_array[:, :, band_index] = enhance_band_array(
            array[:, :, band_index])
    return enhanced_array


def _get_array_dtype(gdal_image):
    return gdal_image.ReadAsArray(0, 0, 0, 0).dtype


def _get_proj4(image):
    spatial_reference = osr.SpatialReference()
    spatial_reference.ImportFromWkt(image.GetProjectionRef())
    return spatial_reference.ExportToProj4().strip()


def _chop(canvas_length, tile_length, interval_length):
    return ((canvas_length - tile_length) / interval_length) + 1


gdal.UseExceptions()
gdal.SetConfigOption('GDAL_NUM_THREADS', 'ALL_CPUS')
