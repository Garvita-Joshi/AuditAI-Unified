import React,{createContext,useContext,useEffect,useState} from 'react';
import {authApi,setAccessToken} from '../api/client';
const Context=createContext(null);
export function AuthProvider({children}){
 const [user,setUser]=useState(null),[loading,setLoading]=useState(true);
 useEffect(()=>{let alive=true;authApi.refresh().then(({data})=>{setAccessToken(data.access_token);if(alive)setUser(data.user);}).catch(()=>{}).finally(()=>{if(alive)setLoading(false);});const expired=()=>setUser(null);window.addEventListener('auditai:session-expired',expired);return()=>{alive=false;window.removeEventListener('auditai:session-expired',expired);};},[]);
 const authenticate=data=>{setAccessToken(data.access_token);setUser(data.user);};
 const logout=async()=>{try{await authApi.logout();}finally{setAccessToken(null);setUser(null);}};
 return <Context.Provider value={{user,loading,authenticate,logout}}>{children}</Context.Provider>;
}
export const useAuth=()=>useContext(Context);
export const isReviewer=user=>Boolean(user?.roles?.some(r=>['maker','checker','admin'].includes(r)));
