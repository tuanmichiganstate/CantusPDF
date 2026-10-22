"""Keyboard-accessible, bounded thumbnail grid for the page organizer."""
import tkinter as tk
from .pdf_layout import map_rect


class PageGrid(tk.Canvas):
    def __init__(self, parent, changed, reorder, toggle, **kwargs):
        super().__init__(parent, background='#eae6dc', highlightthickness=2,
                         highlightbackground='#d9d7cc', highlightcolor='#2e6253', takefocus=True, **kwargs)
        self.changed,self.reorder,self.toggle=changed,reorder,toggle
        self.order=[];self.visible=[];self.chosen=set();self.cards={};self.focus_page=None
        self.images={};self.track={};self.columns=1;self.press=None
        self.bind('<Configure>',lambda e:self.draw())
        self.bind('<ButtonPress-1>',self.pointer_down)
        self.bind('<B1-Motion>',self.pointer_move)
        self.bind('<ButtonRelease-1>',self.pointer_up)
        self.bind('<MouseWheel>',lambda e:self.yview_scroll(-int(e.delta or 0),'units'))
        for key,delta in [('Left',-1),('Right',1),('Up',-1000),('Down',1000)]:
            self.bind('<'+key+'>',lambda e,d=delta:self.navigate(d,e))
        self.bind('<Command-a>',lambda e:self.select_all())
        self.bind('<Control-a>',lambda e:self.select_all())

    def update_pages(self,order,visible,track,images,selection):
        self.order=list(order);self.visible=list(visible);self.track=track;self.images=images
        self.chosen=set(selection)&set(order)
        if self.focus_page not in self.visible:self.focus_page=self.visible[0] if self.visible else None
        self.draw()

    def selection(self):
        return [p for p in self.order if p in self.chosen]

    def selection_set(self,*pages):
        if len(pages)==1 and isinstance(pages[0],(list,tuple,set)):pages=pages[0]
        self.chosen={int(p) for p in pages}&set(self.order)
        self.draw();self.changed()

    def selection_remove(self,*pages):
        self.chosen.difference_update(int(p) for p in pages);self.draw();self.changed()

    def select_all(self):
        self.selection_set(self.order);return 'break'

    def draw(self):
        self.delete('all');self.cards={}
        width=max(220,self.winfo_width());self.columns=max(1,width//190)
        cell=width/self.columns
        kept=set(self.track.get('pages',[]))
        for i,page in enumerate(self.visible):
            x=(i%self.columns)*cell+8;y=(i//self.columns)*280+8;w=cell-16
            self.cards[page]=(x,y,w,264)
            selected=page in self.chosen;included=page in kept
            edge='#2e6253' if selected else '#aebcc7'
            self.create_rectangle(x,y,x+w,y+264,fill='white' if included else '#e2e0d7',outline=edge,width=3 if selected else 1,dash=() if included else (4,3))
            self.create_text(x+10,y+15,anchor='w',text=f'Page {page+1}',fill='#263f38',font=('Helvetica Neue',12,'bold'))
            edit=self.track.get('page_edits',{}).get(str(page),{})
            angle=edit.get('rotation',0)
            self.create_text(x+w-10,y+15,anchor='e',text=f'{angle}°' if angle else '',fill='#2e6253')
            image=self.images.get(page)
            if image:
                iw,ih=image.width(),image.height();ix=x+(w-iw)/2;iy=y+32+(200-ih)/2
                self.create_image(ix,iy,anchor='nw',image=image)
                crop=edit.get('crop',[0,0,1,1])
                if crop!=[0,0,1,1]:
                    l,t,r,b=crop
                    a,c,ww,hh=map_rect([l,t,r-l,b-t],{'rotation':angle})
                    self.create_rectangle(ix+a*iw,iy+c*ih,ix+(a+ww)*iw,iy+(c+hh)*ih,outline='#2e6253',width=2,dash=(4,3))
            else:self.create_text(x+w/2,y+125,text='Loading…',fill='#62675c')
            if not included:
                self.create_rectangle(x+8,y+103,x+w-8,y+132,fill='#e2e0d7',outline='')
                self.create_text(x+w/2,y+118,text='OMITTED',fill='#62675c',font=('Helvetica Neue',11,'bold'))
            self.create_text(x+10,y+246,anchor='w',text='✓ Keep' if included else '↩ Restore',fill='#2e6253',font=('Helvetica Neue',11,'bold'))
            self.create_text(x+w-10,y+246,anchor='e',text='Crop' if edit.get('crop') else '',fill='#62675c')
            if page==self.focus_page and self.focus_get()==self:
                self.create_rectangle(x+4,y+4,x+w-4,y+260,outline='#263f38',dash=(2,2))
        rows=(len(self.visible)+self.columns-1)//self.columns
        self.configure(scrollregion=(0,0,width,rows*280+8))

    def hit(self,x,y):
        x,y=self.canvasx(x),self.canvasy(y)
        for page,(a,b,w,h) in self.cards.items():
            if a<=x<=a+w and b<=y<=b+h:return page
        return None

    def pointer_down(self,event):
        self.focus_set();page=self.hit(event.x,event.y)
        if page is None:return
        old=self.focus_page;self.focus_page=page
        if event.state&1 and old in self.visible:
            a,b=sorted((self.visible.index(old),self.visible.index(page)))
            self.chosen.update(self.visible[a:b+1])
        elif event.state&(4|8|16):
            if page in self.chosen:self.chosen.remove(page)
            else:self.chosen.add(page)
        elif page not in self.chosen:self.chosen={page}
        self.press=(page,event.x,event.y)
        self.draw();self.changed()

    def pointer_move(self,event):
        self.delete('drop')
        target=self.hit(event.x,event.y)
        if self.press and target is not None and target!=self.press[0]:
            x,y,w,h=self.cards[target]
            self.create_rectangle(x-3,y-3,x+w+3,y+h+3,outline='#2e6253',width=3,tags='drop')

    def pointer_up(self,event):
        self.delete('drop')
        if not self.press:return
        page,x,y=self.press;self.press=None;target=self.hit(event.x,event.y)
        if target is None:return
        if abs(event.x-x)+abs(event.y-y)>8:
            if target!=page:self.reorder(page,target)
        elif target==page:
            _,top,_,height=self.cards[page]
            if self.canvasy(event.y)>top+height-34:
                self.selection_set(page);self.toggle(page)

    def navigate(self,delta,event):
        if not self.visible:return 'break'
        step=(-self.columns if delta<0 else self.columns) if abs(delta)==1000 else delta
        old=self.visible.index(self.focus_page) if self.focus_page in self.visible else 0
        new=max(0,min(len(self.visible)-1,old+step));self.focus_page=self.visible[new]
        if event.state&1:self.chosen.update(self.visible[min(old,new):max(old,new)+1])
        else:self.chosen={self.focus_page}
        self.draw();self.changed()
        _,y,_,h=self.cards[self.focus_page]
        top=self.canvasy(0);height=self.winfo_height();total=max(1,int(float(self.cget('scrollregion').split()[3])))
        if y<top:self.yview_moveto(y/total)
        elif y+h>top+height:self.yview_moveto((y+h-height)/total)
        return 'break'
