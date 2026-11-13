"""Two-point alignment in real millimetres; no automatic tolerance or scaling."""
import math

__all__ = ['solve_two_point_alignment']


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label + ' must be finite numeric')
    return float(value)


def _points(values, label):
    if not isinstance(values, (tuple, list)) or len(values) != 2:
        raise ValueError(label + ' requires two points')
    result = []
    for p in values:
        if not isinstance(p, (tuple, list)) or len(p) != 2:
            raise ValueError(label + ' requires XY pairs')
        result.append(tuple(_number(x, label) for x in p))
    return result


def solve_two_point_alignment(source_points, target_points, *, distance_tolerance,
                             angle_tolerance, angle_units='rad', allow_scale=False):
    """Return fit, both angle units and tolerance verdict without editing.

    Distance tolerance is real mm. Angle tolerance bounds the absolute rotation
    between the directed pairs, not a post-fit residual. Scaling is opt-in and
    never bypasses either original-pair tolerance. Coincident pairs are refused.
    """
    src = _points(source_points, 'source_points')
    dst = _points(target_points, 'target_points')
    dt = _number(distance_tolerance, 'distance_tolerance')
    at = _number(angle_tolerance, 'angle_tolerance')
    if angle_units not in ('rad', 'deg'):
        raise ValueError('angle_units must be rad or deg')
    if type(allow_scale) is not bool:
        raise ValueError('allow_scale must be bool')
    if dt < 0 or at < 0 or at > (math.pi if angle_units == 'rad' else 180):
        raise ValueError('Invalid tolerance range')
    ar = at if angle_units == 'rad' else math.radians(at)
    u = tuple(b-a for a,b in zip(src[0],src[1]))
    v = tuple(b-a for a,b in zip(dst[0],dst[1]))
    ls, lt = math.hypot(*u), math.hypot(*v)
    if not all(math.isfinite(x) for x in (*u,*v,ls,lt)):
        raise ValueError('Pair span overflow')
    result = dict(passed=False, reasons=[], source_points_real_mm=src,
                  target_points_real_mm=dst, source_distance_mm=ls, target_distance_mm=lt,
                  distance_difference_mm=lt-ls, distance_tolerance_mm=dt,
                  angle_input_units=angle_units, angle_tolerance_input=at,
                  angle_tolerance_rad=ar, angle_tolerance_deg=math.degrees(ar),
                  allow_scale=allow_scale, coordinate_units='real', transform=None)
    if ls == 0 or lt == 0:
        result['reasons'] = ['Coincident reference points']
        return result
    result.update(angle_tolerance_endpoint_displacement_mm=(2*math.sin(ar/2))*ls,
                  angle_tolerance_lateral_mm=ls*abs(math.sin(ar)),
                  angular_offset_baseline_mm=ls,
                  reference_angle_tolerance_rad=dt/ls,
                  reference_angle_tolerance_deg=math.degrees(dt/ls))
    if not all(math.isfinite(result[k]) for k in ('angle_tolerance_endpoint_displacement_mm','angle_tolerance_lateral_mm','reference_angle_tolerance_rad','reference_angle_tolerance_deg')):
        raise ValueError('Angular tolerance reference amount overflow')
    ux,uy = u[0]/ls,u[1]/ls
    vx,vy = v[0]/lt,v[1]/lt
    angle = math.atan2(ux*vy-uy*vx,ux*vx+uy*vy)
    ratio = lt/ls
    if not math.isfinite(ratio) or ratio <= 0:
        raise ValueError('Scale ratio cannot be represented')
    scale = ratio if allow_scale else 1.
    shift = tuple(b-a for a,b in zip(src[0],dst[0]))
    if not all(math.isfinite(x) for x in shift):
        raise ValueError('Translation overflow')
    result.update(angle_difference_rad=angle, angle_difference_deg=math.degrees(angle),
                  estimated_scale=ratio, applied_scale=scale,
                  endpoint_residuals_mm=[0., abs(lt-scale*ls)])
    if abs(lt-ls) > dt:
        result['reasons'].append('Distance difference exceeds tolerance')
    if abs(angle) > ar:
        result['reasons'].append('Angle difference exceeds tolerance')
    result['passed'] = not result['reasons']
    if result['passed']:
        result['transform'] = dict(base_point=src[0], translation=shift,
                                   rotation=angle, scale_x=scale, scale_y=scale, units='real')
    return result
