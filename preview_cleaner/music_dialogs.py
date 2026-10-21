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
        ttk.Label(frame,text='Select pages · drag to reorder · originals stay unchanged',style='Section.TLabel').pack(anchor='w')
        footer=ttk.Frame(frame);footer.pack(side='bottom',fill='x',pady=(8,0))
        ttk.Button(footer,text='Cancel',command=self.close).pack(side='left')
        ttk.Button(footer,text='Apply pages',command=self.apply,style='Primary.TButton').pack(side='right')
        ttk.Label(frame,textvariable=self.status,wraplength=820).pack(side='bottom',fill='x',pady=4)
        crop=ttk.LabelFrame(frame,text='Trim original displayed edges (%)',padding=8);crop.pack(side='bottom',fill='x',pady=8)
        self.margins=[]
        for label in ('Left','Top','Right','Bottom'):
            ttk.Label(crop,text=label).pack(side='left')
            var=tk.StringVar(self.window,'0');self.margins.append(var)
            ttk.Entry(crop,textvariable=var,width=5).pack(side='left',padx=(4,10))
        ttk.Button(crop,text='Crop selected',command=self.crop).pack(side='left')
        ttk.Button(crop,text='Reset selected',command=self.reset).pack(side='right')
        actions=ttk.Frame(frame);actions.pack(fill='x',pady=8)
        for label,command in [('Select all',self.select_all),('Keep / omit',self.toggle),('↑',lambda:self.move(-1)),('↓',lambda:self.move(1)),('Rotate ↻',self.rotate)]:
            ttk.Button(actions,text=label,command=command,width=12 if len(label)>2 else 3).pack(side='left',padx=(0,5))
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
        self.tree.bind('<ButtonPress-1>',lambda e:setattr(self,'drag_start',self.tree.identify_row(e.y)),add='+')
        self.tree.bind('<ButtonRelease-1>',self.drag_end,add='+')
        self.tree.bind('<<TreeviewSelect>>',self.selection_changed)
        self.refresh();self.thumbnails()

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
            self.tree.insert('','end',iid=str(page),text=f'  Page {page+1}',image=self.images.get(page,''),values=('Keep' if page in self.track['pages'] else 'Omit',label))
        for page in selection:
            self.tree.selection_add(str(page))
        self.status.set(f"{len(self.track['pages'])} kept · {self.track['count']-len(self.track['pages'])} omitted. Crop hides edges; Reset restores them in this project.")
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
            self.order.remove(int(source));self.order.insert(self.order.index(int(target)),int(source))
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
        super().__init__(owner,'Export layout','620x620')
        self.window.minsize(560,600)
        frame=ttk.Frame(self.window,padding=18);frame.pack(fill='both',expand=True)
        self.vars={}
        current=export_options(owner.model)
        for key,label in [('cover','Add title cover'),('contents','Add linked contents (physical PDF page numbers)'),('odd_starts','Start each song on an odd physical page'),('numbers','Add page numbers'),('flatten','Print copy: flatten all annotations'),('optimize','Optimize size without reducing image quality')]:
            variable=tk.BooleanVar(self.window,current[key]);self.vars[key]=variable
            ttk.Checkbutton(frame,text=label,variable=variable).pack(anchor='w',pady=4)
        ttk.Label(frame,text='Flattening fixes notes/comments into this exported copy. Keep the project for editable notes.',wraplength=550,style='Muted.TLabel').pack(fill='x',pady=6)
        for key,label in [('number_start','First printed number'),('number_from','Start on physical PDF page'),('number_margin','Inset from edge (pt)')]:
            row=ttk.Frame(frame);row.pack(fill='x',pady=5)
            ttk.Label(row,text=label).pack(side='left')
            variable=tk.StringVar(self.window,str(current[key]));self.vars[key]=variable
            ttk.Entry(row,textvariable=variable,width=10).pack(side='right')
        self.vars['number_position']=tk.StringVar(self.window,current['number_position'])
        ttk.Combobox(frame,textvariable=self.vars['number_position'],state='readonly',values=('Bottom center','Bottom right','Top center','Top right')).pack(fill='x',pady=5)
        ttk.Label(frame,text='Numbering refuses to cover visible score content. Preview includes cover, blank pages and the final numbering.',wraplength=550,style='Muted.TLabel').pack(fill='x',pady=8)
        ttk.Label(frame,textvariable=self.status,wraplength=550).pack(fill='x')
        actions=ttk.Frame(frame);actions.pack(side='bottom',fill='x',pady=8)
        ttk.Button(actions,text='Cancel',command=self.close).pack(side='left')
        ttk.Button(actions,text='Apply',command=self.apply).pack(side='right')
        ttk.Button(actions,text='Preview export',command=self.preview).pack(side='right',padx=6)

    def values(self):
        values={k:v.get() for k,v in self.vars.items()}
        for k in ('number_start','number_from'):values[k]=int(values[k])
        values['number_margin']=float(values['number_margin'])
        candidate=dict(self.owner.model,version=2,export_options=values)
        export_options(candidate);plan=layout_plan(candidate)
        return candidate,plan

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
        ExportPreview(self.owner,result['pages'])


class ExportPreview(WorkspaceDialog):
    def __init__(self,owner,count):
        super().__init__(owner,'Final PDF preview','800x850')
        self.count=count;self.page=0;self.image=None
        frame=ttk.Frame(self.window,padding=10);frame.pack(fill='both',expand=True)
        bar=ttk.Frame(frame);bar.pack(side='bottom',fill='x')
        ttk.Button(bar,text='‹',command=lambda:self.go(-1)).pack(side='left')
        self.label=ttk.Label(bar);self.label.pack(side='left',padx=8)
        ttk.Button(bar,text='›',command=lambda:self.go(1)).pack(side='left')
        ttk.Button(bar,text='Close preview',command=self.close).pack(side='right')
        self.canvas=tk.Canvas(frame,background='#e9eef3',highlightthickness=0);self.canvas.pack(fill='both',expand=True)
        self.window.update_idletasks();self.render()

    def render(self):
        self.label.configure(text=f'{self.page+1} / {self.count}')
        self.launch(dict(operation='library_preview_page',model=self.owner.model,page=self.page,width=max(100,self.canvas.winfo_width()-20),height=max(100,self.canvas.winfo_height()-20)),self.receive)

    def receive(self,result):
        self.image=tk.PhotoImage(master=self.window,data=result['image'])
        self.canvas.delete('all');self.canvas.create_image(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,image=self.image)

    def go(self,step):
        if self.owner.job:return
        self.page=max(0,min(self.count-1,self.page+step));self.render()
