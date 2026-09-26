import {useEffect, useRef, type ReactNode, type ButtonHTMLAttributes} from 'react';
import {X} from 'lucide-react';

export function Button({children, tone='neutral', ...props}: ButtonHTMLAttributes<HTMLButtonElement> & {tone?:'primary'|'neutral'|'danger'}) {
  return <button {...props} className={`button ${tone} ${props.className||''}`}>{children}</button>;
}
export function Status({value}:{value:string}) {return <span className={`status ${value}`}><span aria-hidden="true"/>{value.replaceAll('_',' ')}</span>;}
export function Empty({title,children}:{title:string;children:ReactNode}) {return <div className="empty"><h2>{title}</h2><div className="muted">{children}</div></div>;}
export function ErrorNotice({message}:{message:string}) {return <div className="notice error" role="alert">{message}</div>;}
export function Inspector({title,children,onClose}:{title:string;children:ReactNode;onClose:()=>void}) {
  const root=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement;
    root.current?.focus();
    const key=(e:KeyboardEvent)=>{if(e.key==='Escape') onClose();};
    document.addEventListener('keydown',key);
    return ()=>{document.removeEventListener('keydown',key);previous?.focus();};
  },[onClose]);
  return <aside ref={root} tabIndex={-1} className="inspector" aria-label={title}>
    <header><h2>{title}</h2><Button aria-label="Close inspector" onClick={onClose}><X size={18}/></Button></header>
    <div className="inspector-body">{children}</div>
  </aside>;
}
