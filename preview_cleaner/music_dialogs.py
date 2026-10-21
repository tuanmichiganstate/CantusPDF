"""Shared page organizer and export controls, using the workspace worker."""
from copy import deepcopy
import tkinter as tk
from tkinter import ttk
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
        super().__init__(owner,'Organize pages · crop / rotate','890x730')
        self.window.minsize(760,620)
        self.model=deepcopy(owner.model)
        self.track=self.model['tracks'][owner.track_index]
        self.order=list(self.track['pages'])+[p for p in range(self.track['count']) if p not in self.track['pages']]
        self.images={}
        self.batch=0
        frame=ttk.Frame(self.window,padding=14); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Arrange your pages',style='Section.TLabel').pack(anchor='w')
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x',pady=(8,0))
        ttk.Button(footer,text='Cancel',command=self.close).pack(side='left')
        ttk.Button(footer,text='Apply pages',command=self.apply,style='Primary.TButton').pack(side='right')
        ttk.Label(frame,textvariable=self.status,wraplength=820).pack(side='bottom',fill='x',pady=4)
        crop=ttk.LabelFrame(frame,text='Crop margins (%) · selected pages',padding=8);crop.pack(side='bottom',fill='x',pady=8)
        self.margins=[]
        for label in ('Left','Top','Right','Bottom'):
            ttk.Label(crop,text=label).pack(side='left')
            var=tk.StringVar(self.window,'0');self.margins.append(var)
            ttk.Entry(crop,textvariable=var,width=5).pack(side='left',padx=(4,10))
        ttk.Button(crop,text='Crop selected',command=self.crop).pack(side='left')
        ttk.Button(crop,text='Reset selected',command=self.reset).pack(side='right')
        crop_actions=ttk.Frame(frame);crop_actions.pack(side='bottom',fill='x')
        ttk.Button(crop_actions,text='Draw crop…',command=self.draw_crop).pack(side='left')
        ttk.Button(crop_actions,text='Detect white margins',command=self.auto_crop).pack(side='left',padx=6)
        actions=ttk.Frame(frame);actions.pack(fill='x',pady=8)
        for label,command in [('Select all',self.select_all),('Keep',lambda:self.set_kept(True)),('Omit',lambda:self.set_kept(False)),('↑',lambda:self.move(-1)),('↓',lambda:self.move(1)),('Rotate ↻',self.rotate)]:
            ttk.Button(actions,text=label,command=command,width=9 if len(label)>2 else 3).pack(side='left',padx=(0,5))
        paging=ttk.Frame(frame);paging.pack(side='bottom',fill='x')
        ttk.Button(paging,text='‹ Thumbnails',command=lambda:self.change_batch(-1)).pack(side='left')
        self.batch_label=ttk.Label(paging);self.batch_label.pack(side='left',padx=8)
        ttk.Button(paging,text='Thumbnails ›',command=lambda:self.change_batch(1)).pack(side='left')
        ttk.Style(self.window).configure('Pages.Treeview',rowheight=148)
        table=ttk.Frame(frame);table.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(table,columns=('state','edit'),show='tree headings',selectmode='extended',style='Pages.Treeview')
        self.tree.heading('#0',text='Page thumbnail');self.tree.column('#0',width=250)
        self.tree.heading('state',text='Output');self.tree.column('state',width=120)
        self.tree.heading('edit',text='Changes');self.tree.column('edit',width=230)
        scroll=ttk.Scrollbar(table,command=self.tree.yview);scroll.pack(side='right',fill='y')
        self.tree.configure(yscrollcommand=scroll.set);self.tree.pack(fill='both',expand=True)
        self.tree.tag_configure('omitted', foreground='#7a8998')
        self.tree.bind('<ButtonPress-1>',lambda e:setattr(self,'drag_start',self.tree.identify_row(e.y)),add='+')
        self.tree.bind('<ButtonRelease-1>',self.drag_end,add='+')
        self.tree.bind('<<TreeviewSelect>>',self.selection_changed)
        self.tree.bind('<space>', lambda event: self.key_action(self.toggle))
        self.tree.bind('<r>', lambda event: self.key_action(self.rotate))
        self.tree.bind('<BackSpace>', lambda event: self.key_action(lambda: self.set_kept(False)))
        self.tree.bind('<Delete>', lambda event: self.key_action(lambda: self.set_kept(False)))
        self.refresh();self.thumbnails()

    def key_action(self, action):
        action()
        return 'break'

    def selected(self):
        return [int(p) for p in self.tree.selection()]

    def selection_changed(self,_=None):
        pages=self.selected()
        if pages:
            crop=self.track.get('page_edits',{}).get(str(pages[0]),{}).get('crop',[0,0,1,1])
            for var,value in zip(self.margins,(crop[0],crop[1],1-crop[2],1-crop[3])):
                var.set(f'{value*100:.2f}')

    def refresh(self, selection=()):
        scroll = self.tree.yview()[0] if self.tree.get_children() else 0
        self.tree.delete(*self.tree.get_children())
        for page in self.order:
            edit=self.track.get('page_edits',{}).get(str(page),{})
            label=('Crop · ' if edit.get('crop') else '')+f"{edit.get('rotation',0)}°"
            self.tree.insert('','end',iid=str(page),text=f'  Page {page+1}',image=self.images.get(page,''),values=('Included' if page in self.track['pages'] else 'Omitted',label), tags=() if page in self.track['pages'] else ('omitted',))
        for page in selection:
            self.tree.selection_add(str(page))
        self.status.set(f"{len(self.track['pages'])} kept · {self.track['count']-len(self.track['pages'])} omitted. Crop hides edges; Reset restores them.")
        self.tree.yview_moveto(scroll)
        self.batch_label.configure(text=f'{self.batch*12+1}–{min(self.batch*12+12,len(self.order))} / {len(self.order)}')

    def thumbnails(self):
        if self.owner.job:
            return
        pages=self.order[self.batch*12:self.batch*12+12]
        self.launch(dict(operation='library_thumbnails',model=self.model,track=self.owner.track_index,pages=pages),self.receive)

    def receive(self,result):
        selected=self.selected()
        for item in result['images']:
            self.images[item['page']]=tk.PhotoImage(master=self.window,data=item['image'])
        self.refresh(selected)

    def change_batch(self,step):
        if self.owner.job:return
        self.batch=max(0,min((len(self.order)-1)//12,self.batch+step))
        self.tree.see(str(self.order[self.batch*12]));self.refresh(self.selected());self.thumbnails()

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())

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
        self.refresh(selected)

    def drag_end(self,event):
        if self.owner.job:return
        source=getattr(self,'drag_start','');target=self.tree.identify_row(event.y)
        if source and target and source!=target:
            position=self.order.index(int(target))
            self.order.remove(int(source));self.order.insert(position,int(source))
            self.track['pages']=[p for p in self.order if p in self.track['pages']]
            self.refresh([int(source)])

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
        controls=ttk.Frame(frame);controls.pack(side='top',fill='x')
        self.original_control=ttk.Checkbutton(controls,text='Original quality',variable=self.original,command=self.render)
        self.original_control.pack(side='left')
        zoom=ttk.Combobox(controls,textvariable=self.zoom,values=('Fit','Detail','Fine detail'),state='readonly',width=12)
        self.zoom_control=zoom
        zoom.pack(side='left',padx=8);zoom.bind('<<ComboboxSelected>>',lambda e:self.render())
        if details:
            ttk.Label(controls,text=f"Original {details['original_size']/1024:.0f} KB → Output {details['size']/1024:.0f} KB").pack(side='left')
        self.approve_button=ttk.Button(bar,text='Approve quality',command=self.approve)
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
        self.label.configure(text=f'{self.page+1} / {self.count}')
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
