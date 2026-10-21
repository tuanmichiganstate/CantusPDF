"""Shared page organizer and export controls, using the workspace worker."""
from copy import deepcopy
import tkinter as tk
from tkinter import ttk
from .page_grid import PageGrid
from .pdf_layout import DEFAULT_EXPORT, export_options, validate_edits, layout_plan


class WorkspaceDialog:
    def __init__(self, owner, title, geometry):
        self.owner=owner
        self.window=tk.Toplevel(owner.window)
        self.window.title(title)
        self.window.geometry(geometry)
        self.window.transient(owner.window)
        self.window.grab_set()
        self.closed=False
        self.status=tk.StringVar(self.window,'')
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        owner.dialog=self

    def launch(self, options, callback):
        if self.owner.job:
            return False
        self.owner.dialog_callback=lambda result: None if self.closed else callback(result)
        if not self.owner.launch(options):
            self.owner.dialog_callback=None
            self.status.set(self.owner.status.get())
            return False
        return True

    def close(self):
        if self.closed:
            return
        self.closed=True
        self.owner.dialog_callback=None
        self.owner.finish()
        self.window.grab_release()
        self.window.destroy()
        self.owner.dialog=None
        self.owner.schedule_render()


class PageOrganizer(WorkspaceDialog):
    def __init__(self, owner):
        super().__init__(owner,'Organize pages · crop / rotate','1140x800')
        self.window.minsize(960,700)
        self.model=deepcopy(owner.model)
        self.track=self.model['tracks'][owner.track_index]
        self.original=deepcopy(self.track)
        self.order=list(self.track['pages'])+[p for p in range(self.track['count']) if p not in self.track['pages']]
        self.images={};self.selection_controls=[];self.batch=0
        self.selection_label=tk.StringVar(self.window,'Select pages to edit')
        frame=ttk.Frame(self.window,padding=14);frame.pack(fill='both',expand=True)
        header=ttk.Frame(frame);header.pack(fill='x',pady=(0,10))
        ttk.Label(header,text='Organize pages',style='Title.TLabel').pack(side='left')
        ttk.Label(header,text=self.track['source_name'],style='Muted.TLabel').pack(side='left',padx=14)
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x',pady=(10,0))
        ttk.Button(footer,text='Cancel',command=self.close).pack(side='left')
        self.apply_button=ttk.Button(footer,text='Apply pages',command=self.apply,style='Primary.TButton')
        self.apply_button.pack(side='right')
        ttk.Button(footer,text='Revert draft',command=self.revert).pack(side='right',padx=8)
        ttk.Label(frame,textvariable=self.status,wraplength=900).pack(side='bottom',fill='x',pady=4)
        body=ttk.Frame(frame);body.pack(fill='both',expand=True)
        shell=ttk.Frame(body,width=280,padding=(10,0,0));shell.pack(side='right',fill='y');shell.pack_propagate(False)
        self.inspector_canvas=tk.Canvas(shell,highlightthickness=0,background='#f7f9fb')
        sidebar_scroll=ttk.Scrollbar(shell,command=self.inspector_canvas.yview);sidebar_scroll.pack(side='right',fill='y')
        self.inspector_canvas.configure(yscrollcommand=sidebar_scroll.set);self.inspector_canvas.pack(fill='both',expand=True)
        inspector=ttk.Frame(self.inspector_canvas)
        item=self.inspector_canvas.create_window(0,0,anchor='nw',window=inspector)
        inspector.bind('<Configure>',lambda e:self.inspector_canvas.configure(scrollregion=self.inspector_canvas.bbox('all')))
        self.inspector_canvas.bind('<Configure>',lambda e:self.inspector_canvas.itemconfigure(item,width=e.width))
        ttk.Label(inspector,text='Selection',style='Section.TLabel').pack(anchor='w')
        ttk.Label(inspector,textvariable=self.selection_label,wraplength=240,style='Muted.TLabel').pack(fill='x',pady=10)
        for label,command in [('Keep selected',lambda:self.set_kept(True)),('Omit selected',lambda:self.set_kept(False)),('Rotate 90°',self.rotate),('Draw crop…',self.draw_crop),('Detect white margins',self.auto_crop),('Reset crop / rotation',self.reset)]:
            button=ttk.Button(inspector,text=label,command=command);button.pack(fill='x',pady=3)
            self.selection_controls.append(button)
        self.crop_section=ttk.Frame(inspector);self.crop_section.pack(fill='x',pady=10)
        self.crop_toggle=ttk.Button(self.crop_section,text='▸ Exact margins (%)',command=self.toggle_margins,style='Quiet.TButton');self.crop_toggle.pack(fill='x')
        self.crop_fields=ttk.Frame(self.crop_section);self.margins=[]
        for label in ('Left','Top','Right','Bottom'):
            row=ttk.Frame(self.crop_fields);row.pack(fill='x',pady=2)
            ttk.Label(row,text=label).pack(side='left')
            var=tk.StringVar(self.window,'0');self.margins.append(var)
            entry=ttk.Entry(row,textvariable=var,width=7);entry.pack(side='right');self.selection_controls.append(entry)
        exact=ttk.Button(self.crop_fields,text='Set margins',command=self.crop);exact.pack(fill='x',pady=3);self.selection_controls.append(exact)
        ttk.Label(inspector,text='Crop outline shows the area to keep. Originals stay unchanged.',wraplength=240,style='Muted.TLabel').pack(fill='x',pady=8)
        left=ttk.Frame(body);left.pack(fill='both',expand=True)
        actions=ttk.Frame(left);actions.pack(fill='x',pady=(0,8))
        ttk.Button(actions,text='Select all',command=self.select_all).pack(side='left')
        for label,step in [('Move earlier',-1),('Move later',1)]:
            button=ttk.Button(actions,text=label,command=lambda d=step:self.move(d));button.pack(side='left',padx=4);self.selection_controls.append(button)
        paging=ttk.Frame(left);paging.pack(side='bottom',fill='x',pady=(8,0))
        self.previous_batch=ttk.Button(paging,text='‹ Previous',command=lambda:self.change_batch(-1));self.previous_batch.pack(side='left')
        self.batch_label=ttk.Label(paging);self.batch_label.pack(side='left',padx=8)
        self.next_batch=ttk.Button(paging,text='Next ›',command=lambda:self.change_batch(1));self.next_batch.pack(side='left')
        scroll=ttk.Scrollbar(left);scroll.pack(side='right',fill='y')
        self.grid=PageGrid(left,self.selection_changed,self.reorder_pages,self.toggle_card,yscrollcommand=scroll.set)
        scroll.configure(command=self.grid.yview);self.grid.pack(fill='both',expand=True)
        self.grid.bind('<space>',lambda e:self.key_action(self.toggle))
        self.grid.bind('<r>',lambda e:self.key_action(self.rotate))
        for key in ('BackSpace','Delete'):self.grid.bind('<'+key+'>',lambda e:self.key_action(lambda:self.set_kept(False)))
        def reveal(event):
            self.window.update_idletasks()
            canvas=self.inspector_canvas;height=max(1,inspector.winfo_height())
            top=event.widget.winfo_rooty()-inspector.winfo_rooty();bottom=top+event.widget.winfo_height()
            if top<canvas.canvasy(0):canvas.yview_moveto(top/height)
            elif bottom>canvas.canvasy(0)+canvas.winfo_height():canvas.yview_moveto((bottom-canvas.winfo_height())/height)
        def bind_scroll(widget):
            widget.bind('<FocusIn>',reveal,add='+')
            widget.bind('<MouseWheel>',lambda e:self.inspector_canvas.yview_scroll(-1 if e.delta>0 else 1,'units'),add='+')
            for child in widget.winfo_children():bind_scroll(child)
        bind_scroll(inspector)
        self.refresh();self.thumbnails()

    def revert(self):
        if self.owner.job:return
        self.track.clear();self.track.update(deepcopy(self.original))
        self.order=list(self.track['pages'])+[p for p in range(self.track['count']) if p not in self.track['pages']]
        self.images.clear();self.batch=0;self.refresh();self.thumbnails()

    def changed_pages(self):
        before=self.original['pages'];after=self.track['pages']
        def state(track,p):
            edit=track.get('page_edits',{}).get(str(p),{})
            return (edit.get('crop',[0,0,1,1]),edit.get('rotation',0))
        return sum((p in before)!=(p in after) or (p in before and p in after and before.index(p)!=after.index(p)) or state(self.original,p)!=state(self.track,p) for p in range(self.track['count']))

    def toggle_card(self,page):
        self.set_kept(page not in self.track['pages'])

    def toggle_margins(self):
        if self.crop_fields.winfo_manager():
            self.crop_fields.pack_forget();self.crop_toggle.configure(text='▸ Exact margins (%)')
        else:
            self.crop_fields.pack(fill='x');self.crop_toggle.configure(text='▾ Exact margins (%)')

    def key_action(self, action):
        action()
        return 'break'

    def selected(self):
        return self.grid.selection()

    def selection_changed(self,_=None):
        pages=self.selected()
        self.selection_label.set(f'{len(pages)} selected · edits apply to these pages' if pages else 'Select pages to edit · drag cards to reorder')
        for control in self.selection_controls:control.configure(state='normal' if pages else 'disabled')
        if pages:
            crop=self.track.get('page_edits',{}).get(str(pages[0]),{}).get('crop',[0,0,1,1])
            for var,value in zip(self.margins,(crop[0],crop[1],1-crop[2],1-crop[3])):
                var.set(f'{value*100:.2f}')

    def refresh(self, selection=()):
        visible=self.order[self.batch*12:self.batch*12+12]
        self.grid.update_pages(self.order,visible,self.track,self.images,selection)
        changes=self.changed_pages()
        self.status.set(f"{len(self.track['pages'])} kept · {self.track['count']-len(self.track['pages'])} omitted · {changes} pages changed")
        self.apply_button.configure(text=f'Apply pages ({changes})' if changes else 'Done')
        self.selection_changed()
        self.batch_label.configure(text=f'{self.batch*12+1}–{min(self.batch*12+12,len(self.order))} of {len(self.order)}')
        self.previous_batch.configure(state='normal' if self.batch else 'disabled')
        self.next_batch.configure(state='normal' if (self.batch+1)*12<len(self.order) else 'disabled')

    def thumbnails(self):
        if self.owner.job:
            return
        pages=[p for p in self.order[self.batch*12:self.batch*12+12] if p not in self.images]
        if not pages:return
        self.launch(dict(operation='library_thumbnails',model=self.model,track=self.owner.track_index,pages=pages,uncropped=True),self.receive)

    def receive(self,result):
        selected=self.selected()
        for item in result['images']:
            self.images[item['page']]=tk.PhotoImage(master=self.window,data=item['image'])
        self.refresh(selected)

    def change_batch(self,step):
        if self.owner.job:return
        self.batch=max(0,min((len(self.order)-1)//12,self.batch+step))
        self.grid.yview_moveto(0);self.refresh(self.selected());self.thumbnails()

    def select_all(self):
        self.grid.select_all()

    def set_kept(self, keep):
        if self.owner.job:
            return
        selected = self.selected()
        kept = set(self.track['pages'])
        if keep:
            kept.update(selected)
        else:
            kept.difference_update(selected)
        if not kept:
            self.status.set('Keep at least one page.')
            return
        self.track['pages'] = [page for page in self.order if page in kept]
        self.refresh(selected)

    def toggle(self):
        if self.owner.job:return
        selected=self.selected()
        keep=set(self.track['pages'])
        if selected and all(p in keep for p in selected):keep.difference_update(selected)
        else:keep.update(selected)
        if not keep:
            self.status.set('Keep at least one page.');return
        self.track['pages']=[p for p in self.order if p in keep]
        self.refresh(selected)

    def move(self,delta):
        if self.owner.job:return
        selected=self.selected(); chosen=set(selected)
        positions=range(len(self.order)) if delta<0 else range(len(self.order)-1,-1,-1)
        for i in positions:
            target=i+delta
            if self.order[i] in chosen and 0<=target<len(self.order) and self.order[target] not in chosen:
                self.order[i],self.order[target]=self.order[target],self.order[i]
        self.track['pages']=[p for p in self.order if p in self.track['pages']]
        self.refresh(selected);self.thumbnails()

    def reorder_pages(self,source,target):
        if self.owner.job:return
        if source not in self.order or target not in self.order or source==target:return
        position=self.order.index(target)
        self.order.remove(source);self.order.insert(position,source)
        self.track['pages']=[p for p in self.order if p in self.track['pages']]
        self.refresh([source]);self.thumbnails()

    def rotate(self):
        if self.owner.job:return
        selected=self.selected()
        for p in selected:
            edit=self.track.setdefault('page_edits',{}).setdefault(str(p),{})
            edit['rotation']=(edit.get('rotation',0)+90)%360
        for page in selected:self.images.pop(page,None)
        self.refresh(selected);self.thumbnails()

    def crop(self):
        if self.owner.job:return
        selected=self.selected();old=deepcopy(self.track.get('page_edits',{}))
        try:
            l,t,r,b=[float(v.get())/100 for v in self.margins]
            for p in selected:self.track.setdefault('page_edits',{}).setdefault(str(p),{})['crop']=[l,t,1-r,1-b]
            validate_edits(self.track)
        except Exception as exc:
            self.track['page_edits']=old;self.status.set(str(exc));return
        for page in selected:self.images.pop(page,None)
        self.refresh(selected);self.thumbnails()

    def draw_crop(self):
        if self.owner.job:return
        pages=self.selected()
        if not pages:
            self.status.set('Select one or more pages first.');return
        self.launch(dict(operation='library_crop_page',model=self.model,track=self.owner.track_index,page=pages[0]),
                    lambda result: CropEditor(self,pages,result))

    def auto_crop(self):
        if self.owner.job:return
        pages=self.selected()
        if not pages:
            self.status.set('Select one or more pages first.');return
        self.launch(dict(operation='library_auto_crop',model=self.model,track=self.owner.track_index,pages=pages),self.receive_crops)

    def receive_crops(self,result):
        pages=[int(p) for p in result['crops']]
        for key,crop in result['crops'].items():
            self.track.setdefault('page_edits',{}).setdefault(key,{})['crop']=crop
            self.images.pop(int(key),None)
        self.refresh(pages);self.thumbnails()

    def reset(self):
        if self.owner.job:return
        selected=self.selected()
        for p in selected:self.track.get('page_edits',{}).pop(str(p),None)
        for page in selected:self.images.pop(page,None)
        self.refresh(selected);self.thumbnails()

    def apply(self):
        if self.owner.job:return
        if self.track!=self.owner.track():
            self.owner.remember();self.owner.model['version']=2
            self.owner.model['tracks'][self.owner.track_index]=deepcopy(self.track)
            self.owner.note_id=None
            self.owner.refresh_tracks();self.owner.load_fields()
        self.close()


class ExportDialog(WorkspaceDialog):
    def __init__(self,owner):
        super().__init__(owner, 'Export layout', '660x540')
        self.window.minsize(620, 520)
        frame = ttk.Frame(self.window, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Make your print copy', style='Title.TLabel').pack(anchor='w')
        self.summary = tk.StringVar(self.window)
        ttk.Label(frame, textvariable=self.summary, style='Muted.TLabel').pack(anchor='w', pady=(5, 12))
        actions = ttk.Frame(frame)
        actions.pack(side='bottom', fill='x', pady=(12, 0))
        ttk.Button(actions, text='Cancel', command=self.close).pack(side='left')
        ttk.Button(actions, text='Apply settings', command=self.apply).pack(side='right')
        ttk.Button(actions, text='Preview PDF', command=self.preview, style='Primary.TButton').pack(side='right', padx=6)
        ttk.Label(frame, textvariable=self.status, wraplength=590).pack(side='bottom', fill='x', pady=6)
        self.tabs = ttk.Notebook(frame)
        self.tabs.pack(fill='both', expand=True)
        panels = {}
        for title in ('Document', 'Page numbers', 'Print options'):
            panel = ttk.Frame(self.tabs, padding=16)
            self.tabs.add(panel, text=title)
            panels[title] = panel
        self.vars = {}
        self.current_options = export_options(owner.model)
        def check(panel, key, label):
            variable = tk.BooleanVar(self.window, self.current_options[key])
            self.vars[key] = variable
            ttk.Checkbutton(panel, text=label, variable=variable).pack(anchor='w', pady=5)
        for key, label in [('cover', 'Title cover'), ('contents', 'Linked contents'), ('odd_starts', 'Start each song on a right-hand page')]:
            check(panels['Document'], key, label)
        ttk.Label(panels['Document'], text='Right-hand starts add blank pages for two-sided printing.\nContents links use the physical PDF page order.', wraplength=540, style='Muted.TLabel').pack(fill='x', pady=12)
        numbers = panels['Page numbers']
        check(numbers, 'numbers', 'Show page numbers')
        self.number_controls = []
        for key, label in [('number_start', 'First number'), ('number_from', 'Start on PDF page'), ('number_margin', 'Inset from edge (pt)')]:
            row = ttk.Frame(numbers)
            row.pack(fill='x', pady=4)
            ttk.Label(row, text=label).pack(side='left')
            variable = tk.StringVar(self.window, str(self.current_options[key]))
            self.vars[key] = variable
            entry = ttk.Entry(row, textvariable=variable, width=10)
            entry.pack(side='right')
            self.number_controls.append(entry)
        self.vars['number_position'] = tk.StringVar(self.window, self.current_options['number_position'])
        position = ttk.Combobox(numbers, textvariable=self.vars['number_position'], state='readonly', values=('Bottom center', 'Bottom right', 'Top center', 'Top right'))
        position.pack(fill='x', pady=6)
        self.number_controls.append(position)
        ttk.Label(numbers, text='Numbers never cover visible score content. Preview checks placement.', wraplength=540, style='Muted.TLabel').pack(fill='x', pady=6)
        printing = panels['Print options']
        check(printing, 'flatten', 'Fix annotations into the exported PDF')
        self.flatten_hint = ttk.Label(printing, wraplength=540, style='Muted.TLabel')
        self.flatten_hint.pack(fill='x', pady=(0, 14))
        check(printing, 'optimize', 'Optimize file size')
        self.vars['image_quality']=tk.StringVar(self.window,self.current_options['image_quality'])
        ttk.Combobox(printing,textvariable=self.vars['image_quality'],state='readonly',
            values=('Original','300 dpi · high quality','150 dpi · smaller file')).pack(fill='x',pady=8)
        ttk.Label(printing,text='Reduced-quality copies need preview approval. Check small notes and staff lines. Monochrome scans stay unchanged.',wraplength=530,style='Muted.TLabel').pack(fill='x')
        for variable in self.vars.values():
            variable.trace_add('write', self.update_options)
        self.update_options()

    def update_options(self, *_):
        enabled = self.vars['numbers'].get()
        for control in self.number_controls:
            control.configure(state=('readonly' if isinstance(control, ttk.Combobox) else 'normal') if enabled else 'disabled')
        self.flatten_hint.configure(text='All annotations become fixed in this copy. Keep your project to edit notes later.' if self.vars['flatten'].get() else 'Annotations stay editable. Private notes stay in your project.')
        try:
            _, plan = self.values()
            blanks = sum(song['blank'] for song in plan['songs'])
            self.summary.set(f"{len(self.owner.model['tracks'])} songs · {plan['total']} pages · {blanks} inserted blanks")
        except Exception:
            self.summary.set('Check the numbering settings')

    def values(self):
        values = {key: variable.get() for key, variable in self.vars.items()}
        if values['numbers']:
            for key in ('number_start', 'number_from'):
                values[key] = int(values[key])
            values['number_margin'] = float(values['number_margin'])
        else:
            for key in ('number_start', 'number_from', 'number_margin', 'number_position'):
                values[key] = self.current_options[key]
        candidate = dict(self.owner.model, version=2, export_options=values)
        export_options(candidate)
        plan = layout_plan(candidate)
        return candidate, plan

    def apply(self,close=True):
        if self.owner.job:return False
        try:candidate,plan=self.values()
        except Exception as exc:self.status.set(str(exc));return False
        if candidate!=self.owner.model:
            self.owner.remember();self.owner.model=candidate
        self.status.set(f"{plan['total']} output pages")
        if close:self.close()
        return True

    def preview(self):
        if self.apply(close=False):
            self.status.set('Building final preview…')
            self.launch(dict(operation='library_preview',model=self.owner.model),self.show_preview)

    def show_preview(self,result):
        self.close()
        self.owner.finish()
        if self.owner.render_pending:
            self.owner.window.after_cancel(self.owner.render_pending);self.owner.render_pending=None
        ExportPreview(self.owner,result['pages'],result)


def size_summary(original, output):
    difference=original-output
    change=f'{abs(difference)/max(1,original):.0%}'
    outcome=f'{change} smaller' if difference>0 else f'{change} larger — Original quality may be preferable' if difference<0 else 'Same size'
    return f'{original/1024:.0f} KB → {output/1024:.0f} KB · {outcome}'


class ExportPreview(WorkspaceDialog):
    def __init__(self,owner,count,details=None):
        super().__init__(owner,'Final PDF preview','900x850')
        self.original=tk.BooleanVar(self.window,False)
        self.zoom=tk.StringVar(self.window,'Fit')
        self.review_model=deepcopy(owner.model)
        self.count=count;self.page=0;self.image=None
        frame=ttk.Frame(self.window,padding=10);frame.pack(fill='both',expand=True)
        bar=ttk.Frame(frame);bar.pack(side='bottom',fill='x')
        ttk.Button(bar,text='‹',command=lambda:self.go(-1)).pack(side='left')
        self.label=ttk.Label(bar);self.label.pack(side='left',padx=8)
        ttk.Button(bar,text='›',command=lambda:self.go(1)).pack(side='left')
        ttk.Button(bar,text='Close preview',command=self.close).pack(side='right')
        self.view_label=tk.StringVar(self.window)
        ttk.Label(frame,textvariable=self.view_label,style='Section.TLabel').pack(anchor='w',pady=(0,8))
        controls=ttk.Frame(frame);controls.pack(side='top',fill='x')
        self.original_control=ttk.Checkbutton(controls,text='Original quality',variable=self.original,command=self.render)
        self.original_control.pack(side='left')
        zoom=ttk.Combobox(controls,textvariable=self.zoom,values=('Fit','Detail','Fine detail'),state='readonly',width=12)
        self.zoom_control=zoom
        zoom.pack(side='left',padx=8);zoom.bind('<<ComboboxSelected>>',lambda e:self.render())
        if details:
            self.size_summary=size_summary(details['original_size'],details['size'])
            ttk.Label(frame,text=self.size_summary,style='Muted.TLabel').pack(anchor='w',pady=8)
        reduced=export_options(owner.model)['image_quality']!='Original'
        self.approve_button=ttk.Button(bar,text='Use this quality' if reduced else 'Done',command=self.approve,style='Primary.TButton')
        self.approve_button.pack(side='right',padx=6)
        area=ttk.Frame(frame);area.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(area,background='#e9eef3',highlightthickness=0)
        vertical=ttk.Scrollbar(area,orient='vertical',command=self.canvas.yview);vertical.pack(side='right',fill='y')
        horizontal=ttk.Scrollbar(area,orient='horizontal',command=self.canvas.xview);horizontal.pack(side='bottom',fill='x')
        self.canvas.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        self.canvas.pack(fill='both',expand=True)
        self.window.update_idletasks();self.render()

    def render(self):
        if self.owner.job:return
        self.label.configure(text=f'Page {self.page+1} of {self.count}')
        self.view_label.set('Original quality · comparison' if self.original.get() else 'Output · '+export_options(self.review_model)['image_quality'])
        size=1600 if self.zoom.get()=='Detail' else 3200 if self.zoom.get()=='Fine detail' else None
        if self.launch(dict(operation='library_preview_page',model=self.owner.model,page=self.page,original=self.original.get(),
            width=size or max(100,self.canvas.winfo_width()-20),height=size or max(100,self.canvas.winfo_height()-20)),self.receive):
            for control in (self.original_control,self.zoom_control,self.approve_button):control.configure(state='disabled')

    def receive(self,result):
        self.image=tk.PhotoImage(master=self.window,data=result['image'])
        self.canvas.delete('all');self.canvas.create_image(0,0,anchor='nw',image=self.image)
        self.canvas.configure(scrollregion=(0,0,self.image.width(),self.image.height()))
        self.original_control.configure(state='normal');self.zoom_control.configure(state='readonly');self.approve_button.configure(state='normal')

    def approve(self):
        if self.owner.job:return
        self.owner.quality_reviewed=deepcopy(self.review_model)
        self.close()

    def go(self,step):
        if self.owner.job:return
        self.page=max(0,min(self.count-1,self.page+step));self.render()


class CropEditor:
    """Draw on the uncropped original; commit only to the organizer draft."""
    def __init__(self, organizer, pages, result):
        self.organizer,self.pages=organizer,pages
        self.window=tk.Toplevel(organizer.window)
        self.window.title('Draw crop — original page')
        self.window.transient(organizer.window);self.window.grab_set()
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        ttk.Label(self.window,text=f'Drag to keep an area · applies to {len(pages)} selected page(s)',padding=10).pack()
        self.image=tk.PhotoImage(master=self.window,data=result['image'])
        self.canvas=tk.Canvas(self.window,width=self.image.width(),height=self.image.height(),highlightthickness=0)
        self.canvas.pack(padx=10)
        self.canvas.create_image(0,0,anchor='nw',image=self.image)
        self.crop=list(organizer.track.get('page_edits',{}).get(str(pages[0]),{}).get('crop',[0,0,1,1]))
        self.start=None;self.rectangle=None
        self.canvas.bind('<ButtonPress-1>',self.begin)
        self.canvas.bind('<B1-Motion>',self.motion)
        self.canvas.bind('<ButtonRelease-1>',self.motion)
        self.status=tk.StringVar(self.window,'Crop hides edges; the original stays in your project.')
        ttk.Label(self.window,textvariable=self.status,padding=8).pack()
        bar=ttk.Frame(self.window,padding=10);bar.pack(fill='x')
        ttk.Button(bar,text='Cancel',command=self.close).pack(side='left')
        ttk.Button(bar,text='Use crop',command=self.apply).pack(side='right')
        self.draw()

    def point(self,event):
        return [max(0,min(1,event.x/self.image.width())),max(0,min(1,event.y/self.image.height()))]

    def begin(self,event):
        self.start=self.point(event)

    def motion(self,event):
        if self.start is None:return
        x,y=self.point(event);a,b=self.start
        self.crop=[min(x,a),min(y,b),max(x,a),max(y,b)]
        self.draw()

    def draw(self):
        if self.rectangle:self.canvas.delete(self.rectangle)
        l,t,r,b=self.crop
        self.rectangle=self.canvas.create_rectangle(l*self.image.width(),t*self.image.height(),r*self.image.width(),b*self.image.height(),outline='#087f8c',width=3)

    def apply(self):
        candidate=deepcopy(self.organizer.track)
        for page in self.pages:
            candidate.setdefault('page_edits',{}).setdefault(str(page),{})['crop']=list(self.crop)
        try:validate_edits(candidate)
        except Exception as exc:self.status.set(str(exc));return
        self.close()
        self.organizer.receive_crops(dict(crops={str(p):list(self.crop) for p in self.pages}))

    def close(self):
        self.window.grab_release();self.window.destroy()
        self.organizer.window.grab_set()
