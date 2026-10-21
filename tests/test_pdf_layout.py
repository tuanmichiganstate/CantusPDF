from copy import deepcopy
from pathlib import Path
import uuid
import pymupdf
import pytest
from preview_cleaner.core import CleanerError
from preview_cleaner.music_library import new_set, import_pdf, import_image, export_pdf, prepare_track, encode_project, load_project, run_library
from preview_cleaner.pdf_layout import map_rect, layout_plan, export_options, validate_edits


def project(tmp_path, rotation=0):
    session=tmp_path/'assets';session.mkdir(exist_ok=True)
    path=tmp_path/'Score.pdf'
    with pymupdf.open() as doc:
        for i in range(2):
            page=doc.new_page(width=600,height=800)
            page.insert_text((100,200),f'Score {i+1}',fontsize=16)
            for y in range(260,500,60):
                for row in range(5):page.draw_line((100,y+row*7),(500,y+row*7))
            page.set_cropbox(pymupdf.Rect(20,30,580,770))
            page.set_rotation(rotation)
        doc.save(path)
    model=new_set('service');model['title']='Chúa nhật - bộ nhạc';model['tracks']=[import_pdf(path,session)]
    return model,session,path


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_crop_rotate_restore_and_project_round_trip(tmp_path,rotation):
    model,session,path=project(tmp_path,rotation)
    original=path.read_bytes();track=model['tracks'][0]
    track['page_edits']={'0':dict(crop=[.1,.1,.9,.9],rotation=90)}
    track['pages']=[1,0]
    with prepare_track(track,session) as prepared, pymupdf.open(stream=export_pdf(model,session,lambda _:None),filetype='pdf') as out:
        assert out[1].rotation==(rotation+90)%360
        assert out[1].get_pixmap().digest==prepared[0].get_pixmap().digest
        assert out[0].get_pixmap().digest==prepared[1].get_pixmap().digest
    saved=tmp_path/'Music.pcset';saved.write_bytes(encode_project(model,session))
    restored,_=load_project(saved,session);assert restored==model
    restored['tracks'][0]['page_edits']={};restored['tracks'][0]['pages']=[0,1]
    with pymupdf.open(path) as before,pymupdf.open(stream=export_pdf(restored,session,lambda _:None),filetype='pdf') as after:
        assert [p.get_pixmap().digest for p in before]==[p.get_pixmap().digest for p in after]
    assert path.read_bytes()==original


@pytest.mark.parametrize('angle',[0,90,180,270])
def test_normalized_note_mapping_is_reversible(angle):
    edit=dict(crop=[.1,.2,.9,.8],rotation=angle)
    rect=[.2,.3,.3,.15]
    assert map_rect(map_rect(rect,edit),edit,inverse=True)==pytest.approx(rect)


def test_cover_contents_odd_starts_numbering_links(tmp_path):
    model,session,_=project(tmp_path)
    first=model['tracks'][0];first.update(title='Bài ca nhập lễ',section='Nhập lễ',pages=[0])
    second=deepcopy(first);second.update(id=uuid.uuid4().hex,title='Bài ca hiệp lễ',section='Hiệp lễ')
    model['tracks'].append(second)
    model['export_options']=dict(cover=True,contents=True,odd_starts=True,numbers=True)
    plan=layout_plan(model)
    assert plan['total']==5 and [s['start'] for s in plan['songs']]==[2,4]
    data=export_pdf(model,session,lambda _:None)
    with pymupdf.open(stream=data,filetype='pdf') as doc:
        assert len(doc)==5
        assert 'Chúa nhật' in doc[0].get_text()
        assert 'Bài ca nhập lễ' in doc[1].get_text()
        assert [link['page'] for link in doc[1].get_links()]==[2,4]
        assert 'Score' in doc[2].get_text() and 'Score' in doc[4].get_text()
        assert 'Score' not in doc[3].get_text()
        assert [list(p.annots())[-1].info['content'] for p in doc]==['1','2','3','4','5']
        assert doc.get_toc()[0][2]==3


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_numbering_on_rotated_crop_and_collision(tmp_path,rotation):
    model,session,_=project(tmp_path,rotation)
    model['export_options']=dict(numbers=True,number_start=9,number_from=2)
    with pymupdf.open(stream=export_pdf(model,session,lambda _:None),filetype='pdf') as out:
        assert not list(out[0].annots())
        assert list(out[1].annots())[-1].info['content']=='9'
    model['tracks'][0]['notes']=[dict(id='note',page=0,text='BOTTOM CONTENT',rect=[.1,.8,.8,.18],scope='song',size=14,print=True)]
    model['export_options']=dict(numbers=True,number_margin=30)
    # Yellow note background occupies the number box.
    with pytest.raises(CleanerError,match='overlaps'):
        export_pdf(model,session,lambda _:None)


def test_flatten_private_notes_and_foreign_annotation(tmp_path):
    model,session,path=project(tmp_path)
    model['tracks'][0]['notes']=[dict(id='a',page=0,text='Hát nhẹ',rect=[.1,.05,.8,.1],scope='song',size=14,print=True),dict(id='b',page=0,text='PRIVATE',rect=[.1,.7,.8,.1],scope='service',size=14,print=False)]
    model['export_options']=dict(flatten=True)
    with pymupdf.open(stream=export_pdf(model,session,lambda _:None),filetype='pdf') as out:
        assert not list(out[0].annots())
        assert 'Hát nhẹ' in out[0].get_text()
        assert 'PRIVATE' not in out[0].get_text()
    assert len(model['tracks'][0]['notes'])==2


def test_image_import_is_lossless_and_portable(tmp_path):
    session=tmp_path/'session';session.mkdir()
    image=tmp_path/'Bài hát.png'
    with pymupdf.open() as d:
        page=d.new_page(width=300,height=400);page.insert_text((50,100),'Image score');pix=page.get_pixmap();pix.save(image)
    original=image.read_bytes();track=import_image(image,session)
    model=new_set('practice');model['tracks']=[track]
    with pymupdf.open(stream=export_pdf(model,session,lambda _:None),filetype='pdf') as out:
        assert len(out)==1 and out[0].get_images()
    assert image.read_bytes()==original and track['source_name']=='Bài hát.png'
    bad=tmp_path/'bad.png';bad.write_text('not an image')
    with pytest.raises(Exception):import_image(bad,session)


def test_limits_and_invalid_crop_options(tmp_path):
    model,session,_=project(tmp_path)
    for crop in ([0,0,.01,1],[-.1,0,1,1],[0,0,float('nan'),1]):
        model['tracks'][0]['page_edits']={'0':dict(crop=crop)}
        with pytest.raises(CleanerError):validate_edits(model['tracks'][0])
    model['tracks'][0]['page_edits']={}
    for options in (dict(number_margin=0),dict(number_from=0),dict(flatten='yes'),dict(number_position='middle')):
        model['export_options']=options
        with pytest.raises(CleanerError):export_options(model)
    model['export_options']=dict(cover=True)
    model['tracks']=[dict(pages=list(range(300)))]
    with pytest.raises(CleanerError,match='300'):layout_plan(model)


def test_worker_thumbnail_preview_and_lossless_optimization(tmp_path):
    model,session,_=project(tmp_path)
    root=tmp_path/'job';root.mkdir()
    base=dict(model=model,session=str(session))
    result=run_library(dict(base,operation='library_thumbnails',track=0,pages=[1,0]),root,lambda _:None)
    assert [p['page'] for p in result['images']]==[1,0]
    assert run_library(dict(base,operation='library_preview'),root,lambda _:None)['pages']==2
    assert run_library(dict(base,operation='library_preview_page',page=1),root,lambda _:None)['image']
    model['export_options']=dict(optimize=False);normal=export_pdf(model,session,lambda _:None)
    model['export_options']['optimize']=True;optimized=export_pdf(model,session,lambda _:None)
    assert len(optimized)<=len(normal)
    with pymupdf.open(stream=normal,filetype='pdf') as a,pymupdf.open(stream=optimized,filetype='pdf') as b:
        assert [p.get_pixmap().digest for p in a]==[p.get_pixmap().digest for p in b]


def test_jpeg_import_and_oversized_header_rejection(tmp_path):
    import struct
    session=tmp_path/'assets';session.mkdir()
    path=tmp_path/'Photo.jpg'
    with pymupdf.open() as doc:
        page=doc.new_page(width=200,height=300);page.insert_text((30,50),'JPEG score')
        path.write_bytes(page.get_pixmap().tobytes('jpeg'))
    assert import_image(path,session)['count']==1
    huge=tmp_path/'huge.png'
    huge.write_bytes(b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',100000,100000))
    with pytest.raises(CleanerError,match='40 megapixels'):import_image(huge,session)


def test_long_contents_multiple_pages_and_legacy_project(tmp_path):
    model,session,_=project(tmp_path)
    track=model['tracks'][0];track['pages']=[0]
    model['tracks']=[dict(deepcopy(track),id=uuid.uuid4().hex,title=f'Bài hát {i+1}') for i in range(15)]
    model['export_options']=dict(contents=True)
    assert layout_plan(model)['contents_pages']==2
    with pymupdf.open(stream=export_pdf(model,session,lambda _:None),filetype='pdf') as output:
        assert len(output)==17
        assert len(output[0].get_links())==14 and output[1].get_links()[0]['page']==16
    model['version']=1;model.pop('export_options')
    old=tmp_path/'old.pcset';old.write_bytes(encode_project(model,session))
    loaded,_=load_project(old,session)
    assert loaded['version']==2 and loaded['tracks']==model['tracks']


def test_flatten_foreign_comments_preserves_appearance(tmp_path):
    model,session,path=project(tmp_path)
    with pymupdf.open(path) as doc:
        page=doc[0];page.add_text_annot((100,600),'Foreign comment')
        other=tmp_path/'With comment.pdf';doc.save(other)
    model['tracks']=[import_pdf(other,session)]
    editable=export_pdf(model,session,lambda _:None)
    model['export_options']=dict(flatten=True)
    flattened=export_pdf(model,session,lambda _:None)
    with pymupdf.open(stream=editable,filetype='pdf') as a,pymupdf.open(stream=flattened,filetype='pdf') as b:
        assert list(a[0].annots()) and not list(b[0].annots())
        assert a[0].get_pixmap().digest==b[0].get_pixmap().digest

@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_auto_crop_original_coordinates_and_immutable_source(tmp_path,rotation):
    model,session,path=project(tmp_path,rotation)
    before=path.read_bytes()
    track=model['tracks'][0]
    track['page_edits']={'0':dict(crop=[.1,.1,.9,.9],rotation=90)}
    result=run_library(dict(operation='library_auto_crop',model=model,session=str(session),track=0,pages=[0,1]),tmp_path,lambda _:None)
    for crop in result['crops'].values():
        assert 0<crop[0]<crop[2]<1 and 0<crop[1]<crop[3]<1
    track['page_edits']={'0':dict(crop=result['crops']['0'])}
    with prepare_track(track,session) as doc:
        assert 'Score 1' in doc[0].get_text()
        assert len(doc[0].get_drawings())==20
    assert path.read_bytes()==before


def test_auto_crop_blank_and_faint_edge_content(tmp_path):
    session=tmp_path/'assets';session.mkdir()
    path=tmp_path/'Faint.pdf'
    with pymupdf.open() as doc:
        doc.new_page(width=300,height=400)
        page=doc.new_page(width=300,height=400)
        page.draw_rect((2,2,298,398),color=(.95,.95,.95),width=2)
        doc.save(path)
    model=new_set();model['tracks']=[import_pdf(path,session)]
    result=run_library(dict(operation='library_auto_crop',model=model,session=str(session),track=0,pages=[0,1]),tmp_path,lambda _:None)
    assert result['crops']=={'0':[0,0,1,1],'1':[0,0,1,1]}


def test_reduced_images_preserve_vectors_notes_and_preview_comparison(tmp_path):
    session=tmp_path/'assets';session.mkdir()
    path=tmp_path/'Scan.pdf'
    with pymupdf.open() as source:
        page=source.new_page(width=200,height=200)
        page.draw_rect((0,0,200,200),color=None,fill=(.96,.94,.9))
        for y in range(20,180,7):page.draw_line((10,y),(190,y),width=.4)
        image=page.get_pixmap(matrix=pymupdf.Matrix(5,5)).tobytes('png')
    with pymupdf.open() as doc:
        page=doc.new_page(width=300,height=400)
        page.insert_image((30,100,230,300),stream=image)
        page.insert_text((30,30),'Vector text stays sharp')
        page.draw_line((30,50),(250,50))
        doc.save(path)
    original=path.read_bytes()
    model=new_set('practice');model['tracks']=[import_pdf(path,session)]
    model['tracks'][0]['notes']=[dict(id='a',page=0,text='Sing softly',rect=[.1,.8,.8,.1],scope='song',size=14,print=True)]
    base=export_pdf(model,session,lambda _:None)
    model['export_options']=dict(image_quality='150 dpi · smaller file')
    reduced=export_pdf(model,session,lambda _:None)
    with pymupdf.open(stream=base,filetype='pdf') as a,pymupdf.open(stream=reduced,filetype='pdf') as b:
        assert a[0].get_text()==b[0].get_text()
        assert a[0].get_drawings()==b[0].get_drawings()
        assert list(b[0].annots())[0].info['content']=='Sing softly'
        assert b[0].get_images()[0][2]<a[0].get_images()[0][2]
    result=run_library(dict(operation='library_preview',model=model,session=str(session)),tmp_path,lambda _:None)
    assert result['size']==len(reduced) and result['original_size']==len(base)
    for original_view in (True,False):
        assert run_library(dict(operation='library_preview_page',model=model,session=str(session),page=0,original=original_view),tmp_path,lambda _:None)['image']
    assert path.read_bytes()==original
    model['export_options']['image_quality']='bad'
    with pytest.raises(CleanerError):export_options(model)
