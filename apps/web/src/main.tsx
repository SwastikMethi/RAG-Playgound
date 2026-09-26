import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {BookOpen, FlaskConical, History, LogOut, Plus} from 'lucide-react';
import {api, hasToken, post, setToken, type Capability, type Project} from './api';
import {Button, Empty, ErrorNotice} from './ui';
import './styles.css';

function App(){
 const [signedIn,signIn]=useState(hasToken());
 const [password,setPassword]=useState('');
 const [error,setError]=useState('');
 const [projects,setProjects]=useState<Project[]>([]);
 const [project,setProject]=useState('');
 const [mode,setMode]=useState('live');
 const [capabilities,setCapabilities]=useState<Capability[]>([]);
 const [name,setName]=useState('');
 useEffect(()=>{if(!signedIn)return; Promise.all([
   api<{items:Project[]}>('/projects'),api<{mode:string;items:Capability[]}>('/system/capabilities')
 ]).then(([p,c])=>{setProjects(p.items);setProject(p.items[0]?.id||'');setMode(c.mode);setCapabilities(c.items);setError('');})
 .catch(e=>setError(e.message));},[signedIn]);
 async function login(e:React.FormEvent){e.preventDefault();setToken(password);try{await api('/system/profiles');signIn(true);setPassword('');}catch(e){setToken('');setError((e as Error).message);}}
 async function addProject(e:React.FormEvent){e.preventDefault();try{const p=await post<Project>('/projects',{name});setProjects([...projects,p]);setProject(p.id);setName('');}catch(e){setError((e as Error).message);}}
 if(!signedIn)return <main className="login"><div className="brand"><FlaskConical/> RAG Playground</div><h1>Your documents.<br/>Different ways to find answers.</h1><p className="muted">A private workspace for exploring retrieval.</p>
   <form onSubmit={login}><label>Application token<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required/></label><Button tone="primary" type="submit">Open workspace</Button></form>{error&&<ErrorNotice message={error}/>}<p className="caption">The token stays in this browser session.</p></main>;
 return <div className="shell"><aside className="rail"><a className="brand" href="/"><FlaskConical size={22}/><span>RAG<br/>Playground</span></a><label className="caption">WORKSPACE<select value={project} onChange={e=>setProject(e.target.value)} aria-label="Project">{projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}{!projects.length&&<option value="">Create a project</option>}</select></label><nav><button className="active"><FlaskConical size={18}/>Playground</button><button><BookOpen size={18}/>Sources</button><button><History size={18}/>History</button></nav><Button onClick={()=>{setToken('');signIn(false);setProjects([]);}}><LogOut size={16}/>Lock workspace</Button></aside>
 <main className="workspace"><header className="page-heading"><div><div className="eyebrow">EXPLORE · COMPARE · UNDERSTAND</div><h1>Retrieval, made visible.</h1><p className="muted">Ask once. Inspect the evidence. Decide what works.</p></div><span className="caption">Private workspace</span></header>
 {mode!=='live'&&<div className="notice">Fixture demonstration · synthetic model responses</div>}{error&&<ErrorNotice message={error}/>}
 {!project?<Empty title="Start with a project"><p>Keep a set of documents and comparisons together.</p><form onSubmit={addProject} className="inline-form"><input aria-label="Project name" placeholder="e.g. Support knowledge" value={name} onChange={e=>setName(e.target.value)} maxLength={120} required/><Button tone="primary" type="submit"><Plus size={16}/>Create project</Button></form></Empty>:<section className="panel"><h2>Your retrieval workspace</h2><p className="muted">Add source documents, prepare a technique, then ask a question.</p><div className="technique-grid">{capabilities.map(c=><article key={c.technique}><h3>{c.display_name}</h3><p>{c.description}</p>{!c.available&&<p className="caption">{c.unavailable_reason}</p>}</article>)}</div></section>}
 </main></div>;
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
