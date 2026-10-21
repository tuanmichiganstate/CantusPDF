"""Reversible page geometry and print-layout options for music projects."""
from copy import deepcopy
import html
import math
import pymupdf
from .core import CleanerError, MAX_PAGES

DEFAULT_EXPORT = dict(cover=False, contents=False, odd_starts=False, numbers=False,
                      number_start=1, number_from=1, number_position='Bottom center',
                      number_margin=18, flatten=False, optimize=True, image_quality="Original")


def export_options(model):
    options = dict(DEFAULT_EXPORT, **model.get('export_options', {}))
    if set(options) != set(DEFAULT_EXPORT):
        raise CleanerError('Unknown export option.')
    for key in ('cover', 'contents', 'odd_starts', 'numbers', 'flatten', 'optimize'):
        if type(options[key]) is not bool:
            raise CleanerError('Invalid export option: ' + key)
    for key in ('number_start', 'number_from'):
        if type(options[key]) is not int or not 1 <= options[key] <= 9999:
            raise CleanerError('Page numbering values must be 1–9999.')
    if options['number_position'] not in ('Bottom center', 'Bottom right', 'Top center', 'Top right'):
        raise CleanerError('Invalid page number position.')
    if options['image_quality'] not in ('Original', '300 dpi · high quality', '150 dpi · smaller file'):
        raise CleanerError('Invalid image quality preset.')
    margin = options['number_margin']
    if type(margin) not in (int, float) or not math.isfinite(margin) or not 4 <= margin <= 100:
        raise CleanerError('Number inset must be 4–100 pt.')
    return options


def validate_edits(track):
    edits = track.get('page_edits', {})
    if not isinstance(edits, dict) or len(edits) > track['count']:
        raise CleanerError('Invalid page edits.')
    for key, edit in edits.items():
        if key not in {str(i) for i in range(track['count'])} or not isinstance(edit, dict):
            raise CleanerError('Invalid edited page.')
        if set(edit) - {'crop', 'rotation'} or edit.get('rotation', 0) not in (0, 90, 180, 270):
            raise CleanerError('Page rotation must be a multiple of 90 degrees.')
        crop = edit.get('crop', [0, 0, 1, 1])
        if not isinstance(crop, list) or len(crop) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in crop):
            raise CleanerError('Invalid crop rectangle.')
        l, t, r, b = crop
        if not (0 <= l < r <= 1 and 0 <= t < b <= 1 and r-l >= .05 and b-t >= .05):
            raise CleanerError('Crop must keep at least 5% of each page dimension.')


def rotate_point(x, y, rotation):
    return {0: (x,y), 90: (1-y,x), 180: (1-x,1-y), 270: (y,1-x)}[rotation]


def map_rect(rect, edit, inverse=False):
    """Map normalized original displayed coordinates to/from edited view."""
    x,y,w,h = rect
    l,t,r,b = edit.get('crop', [0,0,1,1])
    angle = edit.get('rotation', 0)
    points=[]
    for px,py in ((x,y),(x+w,y),(x,y+h),(x+w,y+h)):
        if inverse:
            px,py=rotate_point(px,py,(-angle)%360)
            points.append((l+px*(r-l),t+py*(b-t)))
        else:
            points.append(rotate_point((px-l)/(r-l),(py-t)/(b-t),angle))
    xs,ys=zip(*points)
    return [min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys)]


def apply_geometry(doc, track):
    for key, edit in track.get('page_edits', {}).items():
        page=doc[int(key)]
        l,t,r,b=edit.get('crop',[0,0,1,1])
        box=page.rect
        crop=pymupdf.Rect(l*box.width,t*box.height,r*box.width,b*box.height)*page.derotation_matrix
        offset=page.cropbox_position
        crop += (offset.x,offset.y,offset.x,offset.y)
        page.set_cropbox(crop)
        page.set_rotation((page.rotation+edit.get('rotation',0))%360)


def layout_plan(model):
    options=export_options(model)
    contents_pages=math.ceil(len(model['tracks'])/14) if options['contents'] else 0
    prefix=int(options['cover'])+contents_pages
    cursor=prefix
    songs=[]
    for track in model['tracks']:
        blank=bool(options['odd_starts'] and cursor%2)
        cursor+=int(blank)
        songs.append(dict(start=cursor,blank=blank,count=len(track['pages'])))
        cursor+=len(track['pages'])
    if cursor>MAX_PAGES:
        raise CleanerError('Print layout exceeds 300 pages, including cover, contents and blanks.')
    return dict(prefix=prefix,contents_pages=contents_pages,songs=songs,total=cursor)


def text_box(page, rect, text, size=14, align='left'):
    spare,_=page.insert_htmlbox(rect,'<div>'+html.escape(text).replace('\n','<br>')+'</div>',
        css=f'* {{font-family: sans-serif; font-size: {size}pt; color: #123a56;}} div {{text-align: {align};}}',scale_low=1)
    if spare<0:
        raise CleanerError('Layout text is too long. Shorten the collection or song title.')


def add_front_matter(doc, model, plan):
    options=export_options(model)
    if options['cover']:
        page=doc.new_page(width=595,height=842)
        text_box(page,pymupdf.Rect(48,100,547,400),model['title'],30,'center')
        text_box(page,pymupdf.Rect(48,450,547,600),f"{len(model['tracks'])} bài hát",16,'center')
    for part in range(plan['contents_pages']):
        page=doc.new_page(width=595,height=842)
        text_box(page,pymupdf.Rect(42,35,553,85),'Mục lục',24)
        for row,index in enumerate(range(part*14,min((part+1)*14,len(model['tracks'])))):
            track=model['tracks'][index]; y=100+row*48
            title=(track['section']+' · ' if track['section'] else '')+(track['title'] or track['source_name'])
            physical=plan['songs'][index]['start']+1
            # Always physical page destinations; numbering may start elsewhere.
            text_box(page,pymupdf.Rect(42,y,490,y+46),title,11)
            text_box(page,pymupdf.Rect(495,y,553,y+46),str(physical),11,'right')


def add_contents_links(doc, model, plan):
    offset=int(export_options(model)['cover'])
    for i, song in enumerate(plan['songs']):
        if plan['contents_pages']:
            y=100+(i%14)*48
            doc[offset+i//14].insert_link({'kind':pymupdf.LINK_GOTO,'from':pymupdf.Rect(42,y,553,y+46),'page':song['start'],'to':pymupdf.Point(0,0)})


def add_page_numbers(doc, options):
    if not options['numbers']:
        return
    for index in range(options['number_from']-1,len(doc)):
        page=doc[index]; box=page.rect; inset=options['number_margin']
        right='right' in options['number_position'].lower()
        top=options['number_position'].startswith('Top')
        x=box.width-inset-54 if right else (box.width-54)/2
        y=inset if top else box.height-inset-16
        visible=pymupdf.Rect(x,y,x+54,y+16)
        if not box.contains(visible):
            raise CleanerError('Page is too small for the selected number inset.')
        # Refuse to cover score content, including raster scans and annotations.
        pix=page.get_pixmap(clip=visible,alpha=False,colorspace=pymupdf.csRGB)
        if any(value<240 for value in pix.samples):
            raise CleanerError(f'Page {index+1}: numbering overlaps content. Change position/inset or disable numbering.')
        number=str(options['number_start']+index-(options['number_from']-1))
        annot=page.add_freetext_annot(visible*page.derotation_matrix,number,fontsize=10,
            fontname='Helv',text_color=(.07,.23,.34),align=2 if right else 1,rotate=page.rotation)
        annot.set_info(title='Preview Cleaner',subject='PreviewCleanerPageNumber')
        annot.set_flags(pymupdf.PDF_ANNOT_IS_PRINT)
