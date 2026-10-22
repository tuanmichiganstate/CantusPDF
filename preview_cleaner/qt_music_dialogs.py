"""Qt page organization, reversible crop, and reviewed export layout."""
from copy import deepcopy

from PySide6.QtCore import Qt, QSize, QRectF
from PySide6.QtGui import QIcon, QColor, QPen
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QListWidget, QListWidgetItem, QAbstractItemView, QCheckBox, QSpinBox, QDoubleSpinBox,
    QComboBox, QTabWidget, QDialogButtonBox)
from .qt_common import JobRunner, image_from_result, warn
from .qt_prepare import label, button, ScoreView
from .pdf_layout import export_options, layout_plan
from .music_library import validate_model


class WorkerDialog(QDialog):
    def __init__(self, owner, title):
        super().__init__(owner)
        self.owner=owner; self.shell=owner.shell
        self.setWindowTitle(title)
        self.runner=JobRunner(self.shell,self)
        self.status=label('', 'muted'); self.status.setWordWrap(True)
        self.runner.progress.connect(self.status.setText)
        self.runner.failure.connect(lambda text:(self.status.setText(text),warn(self,text)))
        self.finished.connect(self.cleanup)

    def launch(self, operation, callback, **options):
        return self.runner.start(dict(operation=operation,session=self.owner.session,**options),callback)

    def cleanup(self, *_):
        self.runner.cancel()
        if self.runner in self.shell.runners: self.shell.runners.remove(self.runner)


class PageOrganizer(WorkerDialog):
    def __init__(self, owner):
        super().__init__(owner,'Organize / crop pages')
        self.resize(1040,720); self.setMinimumSize(820,580)
        self.model=deepcopy(owner.model); self.initial=deepcopy(self.model)
        self.index=owner.track_index; self.track=self.model['tracks'][self.index]
        self.order=self.track['pages']+[i for i in range(self.track['count']) if i not in self.track['pages']]
        self.kept=set(self.track['pages']); self.batch=0; self.loading=False
        root=QVBoxLayout(self)
        root.addWidget(label('Shape the pages, keep the music', 'title'))
        root.addWidget(label('Crop hides page edges; it is reversible and is not redaction.', 'muted'))
        row=QHBoxLayout()
        for text,fn in [('Select all',self.select_all),('Keep',lambda:self.keep(True)),('Omit',lambda:self.keep(False)),
                        ('↑',lambda:self.move(-1)),('↓',lambda:self.move(1)),('Rotate ↻',self.rotate),('Reset selected',self.reset)]:
            row.addWidget(button(text,fn))
        root.addLayout(row)
        self.grid=QListWidget(); self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust); self.grid.setIconSize(QSize(120,160))
        self.grid.setGridSize(QSize(155,205)); self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.grid.itemChanged.connect(self.checked)
        self.grid.itemSelectionChanged.connect(self.selection_changed)
        root.addWidget(self.grid,1)
        nav=QHBoxLayout()
        nav.addWidget(button('← Thumbnails',lambda:self.change_batch(-1),'quiet'))
        self.count=label('', 'muted'); nav.addWidget(self.count); nav.addStretch()
        nav.addWidget(button('Thumbnails →',lambda:self.change_batch(1),'quiet')); root.addLayout(nav)
        margins=QHBoxLayout(); self.margins=[]
        for text in ['Left %','Top %','Right %','Bottom %']:
            margins.addWidget(label(text,'muted')); spin=QDoubleSpinBox();spin.setRange(0,95);spin.setDecimals(1)
            spin.setSingleStep(1);margins.addWidget(spin);self.margins.append(spin)
        margins.addWidget(button('Apply margins',self.crop));root.addLayout(margins)
        tools=QHBoxLayout()
        tools.addWidget(button('Draw crop…',self.draw_crop));tools.addWidget(button('Detect white margins',self.auto_crop))
        tools.addStretch();tools.addWidget(button('Revert draft',self.revert,'quiet'));root.addLayout(tools)
        root.addWidget(self.status)
        actions=QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Apply)
        actions.rejected.connect(self.reject);actions.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        root.addWidget(actions)
        self.refresh()

    def selected(self):
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.grid.selectedItems()]

    def sync_order(self):
        start=self.batch*12
        self.order[start:start+self.grid.count()]=[self.grid.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.grid.count())]

    def refresh(self,selection=None):
        self.runner.cancel(); self.loading=True; self.grid.clear()
        for page in self.order[self.batch*12:(self.batch+1)*12]:
            edit=self.track.get('page_edits',{}).get(str(page),{})
            text=f'Page {page+1}' + (' · Omitted' if page not in self.kept else '')
            if edit: text+='\n'+('Crop ' if 'crop' in edit else '')+str(edit.get('rotation',0))+'°'
            item=QListWidgetItem(text);item.setData(Qt.ItemDataRole.UserRole,page)
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if page in self.kept else Qt.CheckState.Unchecked)
            item.setForeground(QColor('#263f38' if page in self.kept else '#85877d'))
            self.grid.addItem(item);item.setSelected(page in (selection or []))
        self.loading=False
        self.count.setText(f'{len(self.kept)} kept / {self.track["count"]} · Thumbnails {self.batch+1}/{(len(self.order)+11)//12}')
        pages=self.order[self.batch*12:(self.batch+1)*12]
        def receive(result):
            by_page={r['page']:image_from_result(r) for r in result['images']}
            for i in range(self.grid.count()):
                item=self.grid.item(i);pix=by_page.get(item.data(Qt.ItemDataRole.UserRole))
                if pix is not None:item.setIcon(QIcon(pix))
        self.launch('library_thumbnails',receive,model=self.model,track=self.index,pages=pages,uncropped=True)

    def checked(self,item):
        if self.loading:return
        page=item.data(Qt.ItemDataRole.UserRole)
        if item.checkState()==Qt.CheckState.Checked:self.kept.add(page)
        else:self.kept.discard(page)
        self.count.setText(f'{len(self.kept)} kept / {self.track["count"]}')

    def selection_changed(self):
        self.all_pages=False
        pages=self.selected()
        if pages:
            l,t,r,b=self.track.get('page_edits',{}).get(str(pages[0]),{}).get('crop',[0,0,1,1])
            for spin,value in zip(self.margins,[l*100,t*100,(1-r)*100,(1-b)*100]):spin.setValue(value)

    def select_all(self):
        # Selection spans every page for multi-page crop/rotation operations.
        self.grid.selectAll();self.all_pages=True
        self.status.setText('All pages selected, including other thumbnail groups.')

    def targets(self):
        return list(self.order) if getattr(self,'all_pages',False) else self.selected()

    def change_batch(self,delta):
        self.sync_order();self.batch=max(0,min((len(self.order)-1)//12,self.batch+delta));self.all_pages=False;self.refresh()

    def keep(self,value):
        pages=self.targets();self.sync_order()
        self.kept.update(pages) if value else self.kept.difference_update(pages)
        self.refresh(pages)

    def move(self,delta):
        self.sync_order();pages=self.selected()
        if delta>0:pages=list(reversed(pages))
        for page in pages:
            i=self.order.index(page);j=max(0,min(len(self.order)-1,i+delta))
            self.order.insert(j,self.order.pop(i))
        self.refresh(pages)

    def edit(self,page):
        return self.track.setdefault('page_edits',{}).setdefault(str(page),{})

    def rotate(self):
        pages=self.targets();self.sync_order()
        for page in pages:
            edit=self.edit(page);edit['rotation']=(edit.get('rotation',0)+90)%360
        self.refresh(pages)

    def crop(self):
        l,t,r,b=[s.value()/100 for s in self.margins]
        if l+r>=.95 or t+b>=.95:warn(self,'Keep at least 5% of each page dimension.');return
        pages=self.targets();self.sync_order()
        for page in pages:self.edit(page)['crop']=[l,t,1-r,1-b]
        self.refresh(pages)

    def reset(self):
        pages=self.targets();self.sync_order()
        for page in pages:self.track.setdefault('page_edits',{}).pop(str(page),None)
        self.refresh(pages)

    def revert(self):
        self.model=deepcopy(self.initial);self.track=self.model['tracks'][self.index]
        self.order=self.track['pages']+[i for i in range(self.track['count']) if i not in self.track['pages']]
        self.kept=set(self.track['pages']);self.all_pages=False;self.refresh()

    def auto_crop(self):
        pages=self.targets();self.sync_order()
        if not pages:return
        def receive(result):
            for key,crop in result['crops'].items():self.edit(int(key))['crop']=crop
            self.refresh(pages);self.status.setText('Suggested crops applied to this draft. Review before applying pages.')
        self.launch('library_auto_crop',receive,model=self.model,track=self.index,pages=pages)

    def draw_crop(self):
        pages=self.targets()
        if not pages:return
        def receive(result):
            dialog=CropDialog(self,image_from_result(result))
            if dialog.exec()==QDialog.DialogCode.Accepted:
                for page in pages:self.edit(page)['crop']=dialog.crop
                self.refresh(pages)
        self.launch('library_crop_page',receive,model=self.model,track=self.index,page=pages[0])

    def apply(self):
        self.sync_order()
        if not self.kept:warn(self,'Keep at least one page.');return
        self.track['pages']=[p for p in self.order if p in self.kept]
        try:validate_model(self.model)
        except Exception as exc:warn(self,exc);return
        self.runner.cancel()
        if self.model!=self.owner.model:self.owner.remember();self.owner.model=deepcopy(self.model)
        self.accept()


class CropView(ScoreView):
    def __init__(self,pixmap):
        super().__init__();self.scene().addPixmap(pixmap)
        self.rect=QRectF(0,0,pixmap.width(),pixmap.height());self.start=None;self.box=None;self.crop=[0,0,1,1]
        self.setDragMode(ScoreView.DragMode.NoDrag)

    def clamp(self,event):
        p=self.mapToScene(event.position().toPoint())
        return max(0,min(self.rect.width(),p.x())),max(0,min(self.rect.height(),p.y()))

    def mousePressEvent(self,event):
        self.start=self.clamp(event)

    def mouseMoveEvent(self,event):
        if self.start:
            x,y=self.clamp(event);a,b=self.start
            rect=QRectF(min(a,x),min(b,y),abs(a-x),abs(b-y))
            if self.box:self.scene().removeItem(self.box)
            self.box=self.scene().addRect(rect,QPen(QColor('#2e6253'),2))
            self.crop=[rect.left()/self.rect.width(),rect.top()/self.rect.height(),rect.right()/self.rect.width(),rect.bottom()/self.rect.height()]

    def mouseReleaseEvent(self,event):
        self.mouseMoveEvent(event);self.start=None


class CropDialog(QDialog):
    def __init__(self,parent,pixmap):
        super().__init__(parent);self.resize(700,700);self.setWindowTitle('Draw crop')
        layout=QVBoxLayout(self);layout.addWidget(label('Drag a rectangle around the content to keep.','muted'))
        self.view=CropView(pixmap);layout.addWidget(self.view,1)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Apply)
        buttons.rejected.connect(self.reject);buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        layout.addWidget(buttons)

    def apply(self):
        l,t,r,b=self.view.crop
        if r-l<.05 or b-t<.05:warn(self,'Keep at least 5% of each page dimension.');return
        self.crop=self.view.crop;self.accept()


class ExportLayout(WorkerDialog):
    def __init__(self,owner):
        super().__init__(owner,'Export layout');self.resize(650,580)
        root=QVBoxLayout(self);root.addWidget(label('Prepare the final collection','title'))
        tabs=QTabWidget();root.addWidget(tabs,1);self.fields={}
        current=export_options(owner.model)
        for title,keys in [('Document',['cover','contents','odd_starts']),('Page numbers',['numbers','number_start','number_from','number_position','number_margin']),('Print options',['flatten','optimize','image_quality'])]:
            page=QWidget();form=QFormLayout(page)
            names={'cover':'Add title cover','contents':'Linked contents','odd_starts':'Start each song on an odd page','numbers':'Add page numbers','number_start':'First printed number','number_from':'Begin on output page','number_position':'Position','number_margin':'Margin (points)','flatten':'Flatten all annotations','optimize':'Optimize PDF size','image_quality':'Image quality'}
            for key in keys:
                value=current[key]
                if type(value) is bool:
                    field=QCheckBox();field.setChecked(value);field.toggled.connect(self.refresh_summary)
                elif key=='number_position' or key=='image_quality':
                    field=QComboBox();field.addItems(['Bottom center','Bottom right','Top center','Top right'] if key=='number_position' else ['Original','300 dpi · high quality','150 dpi · smaller file']);field.setCurrentText(value);field.currentTextChanged.connect(self.refresh_summary)
                else:
                    field=QDoubleSpinBox() if key=='number_margin' else QSpinBox();field.setRange(4,100) if key=='number_margin' else field.setRange(1,9999)
                    field.setValue(value);field.valueChanged.connect(self.refresh_summary)
                self.fields[key]=field;form.addRow(names[key],field)
            if title=='Print options':
                hint=label('Flattening makes all annotations permanent in the exported copy. Keep the editable project. Private notes remain excluded. Reduced images require preview approval.','muted');hint.setWordWrap(True);form.addRow(hint)
            tabs.addTab(page,title)
        self.summary=label('', 'muted');root.addWidget(self.summary);root.addWidget(self.status)
        actions=QHBoxLayout();actions.addWidget(button('Cancel',self.reject,'quiet'));actions.addStretch()
        actions.addWidget(button('Apply',lambda:self.apply()));actions.addWidget(button('Preview final PDF',self.preview,'primary'));root.addLayout(actions)
        self.refresh_summary()

    def values(self):
        options={}
        for key,field in self.fields.items():
            options[key]=field.isChecked() if isinstance(field,QCheckBox) else field.currentText() if isinstance(field,QComboBox) else field.value()
        if not options['numbers']:
            existing=export_options(self.owner.model)
            for key in ['number_start','number_from','number_position','number_margin']:options[key]=existing[key]
        model=deepcopy(self.owner.model);model['export_options']=options;export_options(model);return model

    def refresh_summary(self,*_):
        if not hasattr(self,'summary'):return
        enabled=self.fields['numbers'].isChecked()
        for key in ['number_start','number_from','number_position','number_margin']:self.fields[key].setEnabled(enabled)
        try:self.summary.setText(f"{len(self.owner.model['tracks'])} songs · {layout_plan(self.values())['total']} output pages")
        except Exception as exc:self.summary.setText(str(exc))

    def apply(self,close=True):
        if self.runner.job and not self.runner.rendering:return False
        try:model=self.values();layout_plan(model)
        except Exception as exc:warn(self,exc);return False
        if model!=self.owner.model:self.owner.remember();self.owner.model=model
        if close:self.accept()
        return True

    def preview(self):
        if not self.apply(False):return
        self.snapshot=deepcopy(self.owner.model)
        def receive(result):
            ExportPreview(self.owner,result,self.snapshot).exec()
        self.launch('library_preview',receive,model=self.snapshot)


class ExportPreview(WorkerDialog):
    def __init__(self,owner,result,snapshot):
        super().__init__(owner,'Final PDF preview');self.resize(1100,780)
        self.snapshot=snapshot;self.count=result['pages'];self.page=0
        self.reduced=export_options(snapshot)['image_quality']!='Original'
        root=QVBoxLayout(self);root.addWidget(label('Review the final PDF','title'))
        before,after=result['original_size'],result['size']
        summary=f'{self.count} pages · {after/1024:,.0f} KB'
        if self.reduced:summary+=f' · Original {before/1024:,.0f} KB · {(before-after)/max(before,1):.1%} smaller'
        root.addWidget(label(summary,'muted'))
        row=QHBoxLayout();self.views=[]
        for title in (['Original quality','Selected quality'] if self.reduced else ['Final output']):
            pane=QVBoxLayout();pane.addWidget(label(title,'section'));view=ScoreView();pane.addWidget(view,1)
            bar=QHBoxLayout();bar.addWidget(button('−',lambda _,v=view:v.zoom(1/1.2),'quiet'));bar.addWidget(button('+',lambda _,v=view:v.zoom(1.2),'quiet'));bar.addWidget(button('Fit',view.fit,'quiet'));pane.addLayout(bar)
            self.views.append(view);row.addLayout(pane,1)
        root.addLayout(row,1);root.addWidget(self.status)
        actions=QHBoxLayout();actions.addWidget(button('← Previous',lambda:self.go(-1)));self.number=label('','muted');actions.addWidget(self.number)
        actions.addWidget(button('Next →',lambda:self.go(1)));actions.addStretch();actions.addWidget(button('Close',self.reject,'quiet'))
        self.approve_button=button('Use this quality' if self.reduced else 'Done',self.approve,'primary');actions.addWidget(self.approve_button);root.addLayout(actions)
        self.render()

    def render(self):
        self.number.setText(f'{self.page+1} / {self.count}');self.approve_button.setEnabled(False)
        def receive(result,index):
            view=self.views[index];view.scene().clear();view.scene().addPixmap(image_from_result(result));view.fit()
            if self.reduced and index==0:
                self.launch('library_preview_page',lambda r:receive(r,1),model=self.snapshot,page=self.page,width=1000,height=1400,original=False)
            else:self.approve_button.setEnabled(True)
        self.launch('library_preview_page',lambda r:receive(r,0),model=self.snapshot,page=self.page,width=1000,height=1400,original=self.reduced)

    def go(self,delta):
        self.page=max(0,min(self.count-1,self.page+delta));self.render()

    def approve(self):
        if self.snapshot!=self.owner.model:warn(self,'The project changed. Preview it again before approving.');return
        if self.reduced:self.owner.approved_model=deepcopy(self.snapshot)
        self.accept()
