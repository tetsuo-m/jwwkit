"""Bounded logical geometry of qualified JWW storage, not rendered font/stroke ink."""
import math
from jwwkit._geometry_math import (TAU,point,compose,block_matrix,bounds,union,arc_point,arc_bounds,polygon)
from jwwkit.model.text_metrics import text_endpoint
from jwwkit.model.circular_solid import validate_circular_solid

FIELDS=('bbox','segments','contours','center','representative_points','text_frame','glyph_bbox')


def item(status,value=None,reason=None,method=None):
    return dict(status=status,value=value,reason=reason,method=method)


def exact(value,method):return item('exact',value,method=method)
def unknown(reason):return item('undetermined',reason=str(reason))
def na(reason='No unique applicable quantity'):return item('not_applicable',reason=reason)


def blank():return {k:item('not_requested') for k in FIELDS}


class GeometryLimit(ValueError):pass


class Engine:
    def __init__(self,definitions,presets,fields,text_mode,tolerance,limits,*,real_per_unit=None):
        self.definitions=definitions;self.presets=presets;self.fields=fields;self.text_mode=text_mode
        self.tolerance=tolerance;self.limits=limits;self.nodes=0;self.segment_count=0
        self.real_per_unit=real_per_unit

    def segments(self,segments,approximate=False):
        self.segment_count+=len(segments)
        if self.segment_count>self.limits['max_segments']:return unknown('Segment limit exceeded; no silently truncated geometry')
        return item('approximate' if approximate else 'exact',segments,method='bounded_sagitta' if approximate else 'stored_line_segments')

    def curve_segments(self,center,radius,start,sweep,closed=False):
        if self.tolerance is None:return unknown('Explicit curve_tolerance is required for curve line approximation')
        step=min(math.pi,4*math.asin(math.sqrt(min(1.,self.tolerance/(2*radius)))))
        if step<=0:return unknown('Requested curve tolerance is below representable resolution')
        n=max(4 if closed else 1,math.ceil(abs(sweep)/step))
        if n+self.segment_count>self.limits['max_segments']:return unknown('Segment limit exceeded; analytic contour and bbox remain available')
        pts=[arc_point(center,radius,start+sweep*i/n) for i in range(n+1)]
        if closed:pts[-1]=pts[0]
        result=self.segments([dict(start=a,end=b)for a,b in zip(pts,pts[1:])],True)
        result['max_deviation']=2*radius*math.sin(abs(sweep)/(4*n))**2
        result['requested_max_deviation']=self.tolerance
        return result

    def text_frame(self,r,matrix,similarity):
        try:
            if not similarity:raise ValueError('Nonuniform block text-frame rendering is unverified')
            base=r['base']
            if base['flag']!=0 or base['pen_width']!=0:raise ValueError('Special/flagged/dimension text frame is unverified')
            if type(r['text_type'])is not int or not 0<=r['text_type']<=10:raise ValueError('Unverified text preset')
            sizes={k:r[k]for k in ('size_x','size_y','spacing')}
            if r['text_type']:
                if self.presets.get('status')!='exact':raise ValueError('Text preset table unverified')
                preset=self.presets['values'][r['text_type']-1]
                # Ordinary frames require stored and declared sizes to agree;
                # do not silently resolve contradictory source representations.
                if any(r[k]!=preset[k]for k in sizes):raise ValueError('Stored/preset text sizes disagree')
            expected=text_endpoint((r['start_x'],r['start_y']),r['content'],**sizes,
                                   angle=r['angle'],font_name=r['font_name'],alignment=base['pen_style'])
            saved=(r['end_x'],r['end_y'])
            # Numerical verification only, not an application/drawing tolerance.
            magnitude=max(1.,abs(r['start_x']),abs(r['start_y']),*map(abs,saved),*map(abs,expected))
            length=math.dist((r['start_x'],r['start_y']),expected)
            numeric_guard=max(64*math.ulp(magnitude),1e-9*length)
            real_scale=math.hypot(matrix[0],matrix[2])*self.real_per_unit if self.real_per_unit is not None else None
            if real_scale is None or not math.isfinite(real_scale)or real_scale<=0:
                raise ValueError('Real-coordinate conversion for text roundoff guard is unverified')
            real_guard=numeric_guard*real_scale
            if not math.isfinite(real_guard)or real_guard>=1e-4:
                raise ValueError('Text roundoff guard reaches the real-mm safety cap')
            if math.dist(saved,expected)>numeric_guard:raise ValueError('Saved endpoint does not match the verified ordinary-text rule')
            angle=math.radians(r['angle']);h=r['size_y'];nx,ny=-h*math.sin(angle),h*math.cos(angle)
            corners=[point(matrix,r['start_x'],r['start_y']),point(matrix,*saved),
                     point(matrix,saved[0]+nx,saved[1]+ny),point(matrix,r['start_x']+nx,r['start_y']+ny)]
            return exact(dict(kind='text_frame',corners=corners,bbox=bounds(corners),
                              is_glyph_outline=False,baseline=[corners[0],corners[1]],
                              endpoint_residual_paper_mm=math.dist(saved,expected),numeric_guard_paper_mm=numeric_guard,
                              numeric_guard_real_mm=real_guard,numeric_guard_rule='ordinary-endpoint-roundoff-2'),
                         'saved_start_end_height_angle_with_verified_ordinary_endpoint')
        except (ValueError,KeyError,TypeError,OverflowError)as exc:return unknown(exc)

    def build(self,r,matrix,similarity=True,stack=(),depth=0,path=()):
        self.nodes+=1
        if self.nodes>self.limits['max_children']or depth>self.limits['max_depth']:raise GeometryLimit('Geometry expansion/depth limit exceeded')
        out=blank();out.update(kind=r['type'].lower(),child_path=list(path),parts=[],partial_bbox=None)
        for field in ('text_frame','glyph_bbox'):out[field]=na()
        try:
            kind=r['type']
            if kind in ('BLOCK','DIMENSION'):
                out['center']=na('Composite has no unique geometric center');out['text_frame']=na('Inspect text parts for their individual frames')
                parts=[]
                if kind=='BLOCK':
                    base=r['base']
                    if base['pen_style']not in (0,1,2,3,64,65,66,67)or base['flag']!=0 or base['pen_width']!=0:raise ValueError('Unverified block reference attributes')
                    number=r['def_number']
                    if number in stack:raise ValueError('Cyclic block definition')
                    if number not in self.definitions:raise ValueError('Missing block definition')
                    local,uniform=block_matrix(r);child_matrix=compose(matrix,local)
                    parts=[self.build(child,child_matrix,similarity and uniform,stack+(number,),depth+1,path+('definition',i)) for i,child in enumerate(self.definitions[number]['entities'])]
                    anchor=point(matrix,r['ref_x'],r['ref_y'])
                    out['representative_points']=exact([dict(point=anchor,point_kind='block_insertion',on_geometry=None)],'stored_block_anchor')
                else:
                    if r['sxf_mode']!=0:raise ValueError('Only verified mode0 dimension geometry is supported')
                    # mode0 auxiliaries retain their storage but are not drawn.
                    parts=[self.build(r[key],matrix,similarity,stack,depth+1,path+(key,)) for key in ('line','text')]
                    out['ignored_storage_parts']=['aux_lines','aux_points']
                    out['representative_points']=exact([dict(point=point(matrix,r['line']['start_x'],r['line']['start_y']),point_kind='dimension_line_start',on_geometry=True)],'active_dimension_line')
                out['parts']=parts
                if not parts:raise ValueError('Empty composite has no geometry')
                boxes=[p['bbox']['value']for p in parts if p['bbox']['status']=='exact']
                out['partial_bbox']=union(boxes)if boxes else None
                out['bbox']=exact(union(boxes),'complete_child_union')if len(boxes)==len(parts)else unknown('A child bbox is undetermined; partial_bbox is not the whole extent')
                for field in ('contours','segments'):
                    statuses=[p[field]['status']for p in parts]
                    if all(s in ('exact','approximate','not_applicable')for s in statuses):
                        values=[x for p in parts for x in (p[field]['value']or [])]
                        out[field]=item('approximate'if 'approximate'in statuses else 'exact',values,method='complete_child_union')
                    else:out[field]=unknown('A child '+field+' is undetermined')
                return out
            if kind=='LINE':
                a,b=(point(matrix,r[p+'_x'],r[p+'_y'])for p in ('start','end'))
                out['bbox']=exact(bounds([a,b]),'segment_endpoints')
                out['center']=exact(dict(point=[a[i]/2+b[i]/2 for i in (0,1)],center_kind='segment_midpoint'),'segment_midpoint')
                out['segments']=self.segments([dict(start=a,end=b)])
                out['contours']=exact([dict(kind='polyline',points=[a,b],closed=False,role='open')],'stored_line')
                out['representative_points']=exact([dict(point=p,point_kind=k,on_geometry=True)for p,k in ((a,'start'),(b,'end'),(out['center']['value']['point'],'midpoint'))],'segment_points')
            elif kind=='POINT':
                p=point(matrix,r['x'],r['y']);out['bbox']=exact(bounds([p]),'geometric_point_not_marker_glyph')
                out['center']=exact(dict(point=p,center_kind='point'),'stored_point')
                out['segments']=na('A point has no line segment');out['contours']=exact([dict(kind='point',point=p)],'stored_point')
                out['representative_points']=exact([dict(point=p,point_kind='point',on_geometry=True)],'stored_point')
                out['marker_glyph']=unknown('Point marker glyph/stroke extent is outside geometric-point scope')
            elif kind=='TEXT':
                frame=self.text_frame(r,matrix,similarity);out['text_frame']=frame
                out['glyph_bbox']=unknown('Rendered font glyph outline is not inferred from stored text frame')
                a,b=point(matrix,r['start_x'],r['start_y']),point(matrix,r['end_x'],r['end_y'])
                out['representative_points']=exact([dict(point=p,point_kind=k,on_geometry=None)for p,k in ((a,'text_start'),(b,'text_end'))],'stored_text_anchors_not_glyph_points')
                if self.text_mode=='frame'and frame['status']=='exact':
                    pts=frame['value']['corners'];out['bbox']=exact(bounds(pts),'text_frame_not_glyph')
                    out['contours']=exact([dict(kind='polyline',points=pts,closed=True,role='text_frame')],'logical_text_frame')
                    out['segments']=self.segments([dict(start=a,end=b)for a,b in zip(pts,pts[1:]+pts[:1])])
                    out['center']=exact(dict(point=[sum(p[i]/4 for p in pts)for i in (0,1)],center_kind='text_frame_center_not_glyph'),'logical_text_frame')
                else:
                    reason=frame['reason']if self.text_mode=='frame'else 'Glyph geometry is undetermined; choose text_mode=frame for the separate logical frame'
                    for field in ('bbox','contours','segments','center'):out[field]=unknown(reason)
            elif kind=='SOLID':
                pts,centroid,orientation=polygon([point(matrix,r[f'point{i}_x'],r[f'point{i}_y'])for i in (1,3,2,4)])
                out['bbox']=exact(bounds(pts),'qualified_perimeter_vertices')
                out['contours']=exact([dict(kind='polyline',points=pts,closed=True,role='outer',orientation=orientation,filled=True)],'simple_solid_polygon')
                out['segments']=self.segments([dict(start=a,end=b)for a,b in zip(pts,pts[1:]+pts[:1])])
                out['center']=exact(dict(point=centroid,center_kind='area_centroid'),'signed_polygon_area')
                out['representative_points']=exact([dict(point=p,point_kind='vertex',on_geometry=True)for p in pts],'polygon_vertices')
            elif kind in ('CIRCLE','ARC','CIRCLE_SOLID'):
                center=point(matrix,r['center_x'],r['center_y'])
                out['center']=exact(dict(point=center,center_kind='supporting_circle_center'),'stored_center')
                out['representative_points']=exact([dict(point=center,point_kind='circle_center',on_geometry=None if kind=='CIRCLE_SOLID'else False)],'stored_center')
                if r['flatness']!=1 or not similarity:raise ValueError('Ellipse/nonuniform circular transform is undetermined; center alone is known')
                if kind=='CIRCLE_SOLID':validate_circular_solid(r)
                scale=math.hypot(matrix[0],matrix[2]);radius=r['radius']*scale
                if not math.isfinite(radius)or radius<=0:raise ValueError('Positive finite radius required')
                full=kind=='CIRCLE'or kind=='CIRCLE_SOLID'and (r['base']['pen_style']==105 or r['solid_mode']==100.)
                sweep=TAU if full else r['arc_angle']
                if not math.isfinite(sweep)or not 0<abs(sweep)<=TAU:raise ValueError('Unverified circular sweep')
                angle=r['start_angle']+r['tilt_angle'];direction=point(matrix,r['center_x']+math.cos(angle),r['center_y']+math.sin(angle))
                start=math.atan2(direction[1]-center[1],direction[0]-center[0])
                if matrix[0]*matrix[3]-matrix[1]*matrix[2]<0:sweep=-sweep
                if full:start=0.;sweep=TAU
                contours=[dict(kind='circle'if full else 'arc',center=center,radius=radius,start_angle=start,sweep_angle=sweep,closed=full,role='outer'if kind=='CIRCLE_SOLID'else 'curve')]
                out['bbox']=exact(arc_bounds(center,radius,start,sweep),'analytic_circle_or_arc_extrema')
                center_in_shape=kind=='CIRCLE_SOLID'and r['base']['pen_style']!=105 and (full or abs(sweep)>=math.pi)
                out['representative_points']=exact([dict(point=center,point_kind='circle_center',on_geometry=center_in_shape),dict(point=arc_point(center,radius,start+sweep/2),point_kind='curve_midpoint',on_geometry=True)],'analytic_curve_points')
                if kind=='CIRCLE_SOLID':
                    contours[0]['filled']=True
                    if r['base']['pen_style']==105:
                        inner=r['solid_mode']*scale
                        contours.append(dict(kind='circle',center=center,radius=inner,start_angle=0.,sweep_angle=-TAU,closed=True,role='hole'))
                    elif not full:
                        a,b=arc_point(center,radius,start),arc_point(center,radius,start+sweep)
                        contours.append(dict(kind='polyline',points=[b,a],closed=False,role='chord'))
                out['contours']=exact(contours,'analytic_curve_and_qualified_fill_boundary')
                if 'segments'in self.fields:
                    seg=self.curve_segments(center,radius,start,sweep,full)
                    if seg['status']=='approximate'and kind=='CIRCLE_SOLID':
                        if r['base']['pen_style']==105:
                            second=self.curve_segments(center,inner,0.,-TAU,True)
                            if second['status']=='approximate':seg['value']+=second['value'];seg['max_deviation']=max(seg['max_deviation'],second['max_deviation'])
                            else:seg=unknown(second['reason'])
                        elif not full:
                            closing=self.segments([dict(start=arc_point(center,radius,start+sweep),end=arc_point(center,radius,start))])
                            if closing['status']=='exact':seg['value']+=closing['value']
                            else:seg=unknown(closing['reason'])
                    out['segments']=seg
            else:raise ValueError('Geometry kind is not verified: '+str(kind))
        except (ValueError,KeyError,TypeError,OverflowError)as exc:
            if isinstance(exc,GeometryLimit):raise
            for field in ('bbox','segments','contours'):
                if out[field]['status']=='not_requested':out[field]=unknown(exc)
            if out['center']['status']=='not_requested':out['center']=unknown(exc)
            if out['representative_points']['status']=='not_requested':out['representative_points']=unknown(exc)
        return out
