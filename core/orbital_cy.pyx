# cython: boundscheck=False, wraparound=False, cdivision=True, language_level=3
from libc.math cimport hypot, sqrt, fabs, isnan, NAN
from libc.stdlib cimport malloc, free

cdef double TOL = 1e-7

cdef inline double c_pointdist(double px,double py,double s1x,double s1y,double s2x,double s2y,double nx,double ny,bint infinite) nogil:
    cdef double nl=hypot(nx,ny)
    if nl<1e-12: nl=1.0
    nx/=nl; ny/=nl
    cdef double dx=ny, dy=-nx
    cdef double pd=px*dx+py*dy, s1d=s1x*dx+s1y*dy, s2d=s2x*dx+s2y*dy
    cdef double pn=px*nx+py*ny, s1n=s1x*nx+s1y*ny, s2n=s2x*nx+s2y*ny
    cdef bint a1,a2
    if not infinite:
        a1 = fabs(pd-s1d)<TOL; a2 = fabs(pd-s2d)<TOL
        if (((pd<s1d or a1) and (pd<s2d or a2)) or ((pd>s1d or a1) and (pd>s2d or a2))):
            return NAN
        if a1 and a2 and pn>s1n and pn>s2n:
            return (pn-s1n) if (pn-s1n)<(pn-s2n) else (pn-s2n)
        if a1 and a2 and pn<s1n and pn<s2n:
            return -((s1n-pn) if (s1n-pn)<(s2n-pn) else (s2n-pn))
    if (s1d-s2d)==0: return NAN
    return -(pn - s1n + (s1n-s2n)*(s1d-pd)/(s1d-s2d))

cdef inline double c_segdist(double Ax,double Ay,double Bx,double By,double Ex,double Ey,double Fx,double Fy,double dx,double dy) nogil:
    cdef double nx=dy, ny=-dx
    cdef double rvx=-dx, rvy=-dy
    cdef double dA=Ax*nx+Ay*ny, dB=Bx*nx+By*ny, dE=Ex*nx+Ey*ny, dF=Fx*nx+Fy*ny
    cdef double cA=Ax*dx+Ay*dy, cB=Bx*dx+By*dy, cE=Ex*dx+Ey*dy, cF=Fx*dx+Fy*dy
    cdef double ABmin=dA if dA<dB else dB, ABmax=dA if dA>dB else dB
    cdef double EFmin=dE if dE<dF else dF, EFmax=dE if dE>dF else dF
    if fabs(ABmax-EFmin)<TOL or fabs(ABmin-EFmax)<TOL: return NAN
    if ABmax<EFmin or ABmin>EFmax: return NAN
    cdef double overlap, mM,Mm,MM,mm
    if (ABmax>EFmax and ABmin<EFmin) or (EFmax>ABmax and EFmin<ABmin):
        overlap=1.0
    else:
        mM = ABmax if ABmax<EFmax else EFmax
        Mm = ABmin if ABmin>EFmin else EFmin
        MM = ABmax if ABmax>EFmax else EFmax
        mm = ABmin if ABmin<EFmin else EFmin
        overlap = 1.0 if (MM-mm)==0 else (mM-Mm)/(MM-mm)
    cdef double cABE=(Ey-Ay)*(Bx-Ax)-(Ex-Ax)*(By-Ay)
    cdef double cABF=(Fy-Ay)*(Bx-Ax)-(Fx-Ax)*(By-Ay)
    cdef double ABnx,ABny,EFnx,EFny,ABnl,EFnl,nd
    if fabs(cABE)<TOL and fabs(cABF)<TOL:
        ABnx=By-Ay; ABny=Ax-Bx; ABnl=hypot(ABnx,ABny)
        if ABnl<1e-12: ABnl=1.0
        ABnx/=ABnl; ABny/=ABnl
        EFnx=Fy-Ey; EFny=Ex-Fx; EFnl=hypot(EFnx,EFny)
        if EFnl<1e-12: EFnl=1.0
        EFnx/=EFnl; EFny/=EFnl
        if fabs(ABny*EFnx-ABnx*EFny)<TOL and (ABny*EFny+ABnx*EFnx)<0:
            nd=ABny*dy+ABnx*dx
            if fabs(nd)<TOL: return NAN
            if nd<0: return 0.0
        return NAN
    cdef double best=NAN, d, dBp
    cdef bint have=False
    if fabs(dA-dE)<TOL:
        d=cA-cE; best=d; have=True
    elif fabs(dA-dF)<TOL:
        d=cA-cF; best=d; have=True
    elif dA>EFmin and dA<EFmax:
        d=c_pointdist(Ax,Ay,Ex,Ey,Fx,Fy,rvx,rvy,False)
        if not isnan(d) and fabs(d)<TOL:
            dBp=c_pointdist(Bx,By,Ex,Ey,Fx,Fy,rvx,rvy,True)
            if dBp<0 or fabs(dBp*overlap)<TOL: d=NAN
        if not isnan(d):
            if not have or d<best: best=d; have=True
    if fabs(dB-dE)<TOL:
        d=cB-cE
        if not have or d<best: best=d; have=True
    elif fabs(dB-dF)<TOL:
        d=cB-cF
        if not have or d<best: best=d; have=True
    elif dB>EFmin and dB<EFmax:
        d=c_pointdist(Bx,By,Ex,Ey,Fx,Fy,rvx,rvy,False)
        if not isnan(d) and fabs(d)<TOL:
            dBp=c_pointdist(Ax,Ay,Ex,Ey,Fx,Fy,rvx,rvy,True)
            if dBp<0 or fabs(dBp*overlap)<TOL: d=NAN
        if not isnan(d):
            if not have or d<best: best=d; have=True
    if dE>ABmin and dE<ABmax:
        d=c_pointdist(Ex,Ey,Ax,Ay,Bx,By,dx,dy,False)
        if not isnan(d) and fabs(d)<TOL:
            dBp=c_pointdist(Fx,Fy,Ax,Ay,Bx,By,dx,dy,True)
            if dBp<0 or fabs(dBp*overlap)<TOL: d=NAN
        if not isnan(d):
            if not have or d<best: best=d; have=True
    if dF>ABmin and dF<ABmax:
        d=c_pointdist(Fx,Fy,Ax,Ay,Bx,By,dx,dy,False)
        if not isnan(d) and fabs(d)<TOL:
            dBp=c_pointdist(Ex,Ey,Ax,Ay,Bx,By,dx,dy,True)
            if dBp<0 or fabs(dBp*overlap)<TOL: d=NAN
        if not isnan(d):
            if not have or d<best: best=d; have=True
    if not have: return NAN
    return best

cdef double c_slidedist(double* Ax,double* Ay,int nA,double* Bx,double* By,int nB,double dx,double dy) nogil:
    cdef double dl=hypot(dx,dy)
    if dl<1e-12: return NAN
    dx/=dl; dy/=dl
    cdef double dist=NAN, d
    cdef bint have=False
    cdef int i,j,i2,j2
    for i in range(nB):
        i2=(i+1)%nB
        if fabs(Bx[i]-Bx[i2])<TOL and fabs(By[i]-By[i2])<TOL: continue
        for j in range(nA):
            j2=(j+1)%nA
            if fabs(Ax[j]-Ax[j2])<TOL and fabs(Ay[j]-Ay[j2])<TOL: continue
            d=c_segdist(Ax[j],Ay[j],Ax[j2],Ay[j2],Bx[i],By[i],Bx[i2],By[i2],dx,dy)
            if not isnan(d) and (not have or d<dist):
                if d>0 or fabs(d)<TOL:
                    dist=d; have=True
    return dist if have else NAN

cdef inline bint c_onseg(double Ax,double Ay,double Bx,double By,double px,double py) nogil:
    cdef double lo,hi,cr,dot,L2
    if fabs(Ax-Bx)<TOL and fabs(Ay-By)<TOL: return False
    if fabs(Ax-Bx)<TOL and fabs(px-Ax)<TOL:
        lo = Ay if Ay<By else By
        hi = Ay if Ay>By else By
        return fabs(py-By)>=TOL and fabs(py-Ay)>=TOL and py>lo and py<hi
    if fabs(Ay-By)<TOL and fabs(py-Ay)<TOL:
        lo = Ax if Ax<Bx else Bx
        hi = Ax if Ax>Bx else Bx
        return fabs(px-Bx)>=TOL and fabs(px-Ax)>=TOL and px>lo and px<hi
    if (px<Ax and px<Bx) or (px>Ax and px>Bx): return False
    if (py<Ay and py<By) or (py>Ay and py>By): return False
    cr=(py-Ay)*(Bx-Ax)-(px-Ax)*(By-Ay)
    if fabs(cr)>TOL: return False
    dot=(px-Ax)*(Bx-Ax)+(py-Ay)*(By-Ay)
    if dot<0 or fabs(dot)<TOL: return False
    L2=(Bx-Ax)*(Bx-Ax)+(By-Ay)*(By-Ay)
    if dot>L2 or fabs(dot-L2)<TOL: return False
    return True

def nfp_outer(list Acoords, list Bcoords):
    cdef int nA=len(Acoords), nB=len(Bcoords)
    cdef double* Ax=<double*>malloc(nA*sizeof(double))
    cdef double* Ay=<double*>malloc(nA*sizeof(double))
    cdef double* Bx=<double*>malloc(nB*sizeof(double))
    cdef double* By=<double*>malloc(nB*sizeof(double))
    cdef int capV=8*(nA*nB)+64
    cdef double* cvx=<double*>malloc(capV*sizeof(double))
    cdef double* cvy=<double*>malloc(capV*sizeof(double))
    cdef int i,j,ni,nj,nc,k
    for i in range(nA): Ax[i]=Acoords[i][0]; Ay[i]=Acoords[i][1]
    for i in range(nB): Bx[i]=Bcoords[i][0]; By[i]=Bcoords[i][1]
    cdef int minAi=0, maxBi=0
    for i in range(1,nA):
        if Ay[i]<Ay[minAi]: minAi=i
    for i in range(1,nB):
        if By[i]>By[maxBi]: maxBi=i
    cdef double ox=Ax[minAi]-Bx[maxBi], oy=Ay[minAi]-By[maxBi]
    for i in range(nB): Bx[i]+=ox; By[i]+=oy
    cdef double rx=Bx[0], ry=By[0], sx=rx, sy=ry
    cdef double prevx=0, prevy=0
    cdef bint haveprev=False
    out=[(rx,ry)]
    cdef int ty,ai,bj,pAi,nAi_,pBi,nBi_
    cdef double vAx,vAy,pAx,pAy,nAx,nAy,vBx,vBy,pBx,pBy,nBx,nBy
    cdef double vx,vy,md,d,v2,sc,trx,try_,ux,uy,pux,puy,ul,pl
    cdef int maxiter=10*(nA+nB), it
    cdef bint found=False
    for it in range(maxiter):
        nc=0
        for i in range(nA):
            ni=(i+1)%nA
            for j in range(nB):
                nj=(j+1)%nB
                ty=-1
                if fabs(Ax[i]-Bx[j])<TOL and fabs(Ay[i]-By[j])<TOL: ty=0; ai=i; bj=j
                elif c_onseg(Ax[i],Ay[i],Ax[ni],Ay[ni],Bx[j],By[j]): ty=1; ai=ni; bj=j
                elif c_onseg(Bx[j],By[j],Bx[nj],By[nj],Ax[i],Ay[i]): ty=2; ai=i; bj=nj
                if ty<0: continue
                pAi=ai-1 if ai>0 else nA-1; nAi_=(ai+1)%nA; pBi=bj-1 if bj>0 else nB-1; nBi_=(bj+1)%nB
                vAx=Ax[ai]; vAy=Ay[ai]; pAx=Ax[pAi]; pAy=Ay[pAi]; nAx=Ax[nAi_]; nAy=Ay[nAi_]
                vBx=Bx[bj]; vBy=By[bj]; pBx=Bx[pBi]; pBy=By[pBi]; nBx=Bx[nBi_]; nBy=By[nBi_]
                if ty==0:
                    if nc+4<capV:
                        cvx[nc]=pAx-vAx; cvy[nc]=pAy-vAy; nc+=1
                        cvx[nc]=nAx-vAx; cvy[nc]=nAy-vAy; nc+=1
                        cvx[nc]=vBx-pBx; cvy[nc]=vBy-pBy; nc+=1
                        cvx[nc]=vBx-nBx; cvy[nc]=vBy-nBy; nc+=1
                elif ty==1:
                    if nc+2<capV:
                        cvx[nc]=vAx-vBx; cvy[nc]=vAy-vBy; nc+=1
                        cvx[nc]=pAx-vBx; cvy[nc]=pAy-vBy; nc+=1
                elif ty==2:
                    if nc+2<capV:
                        cvx[nc]=vAx-vBx; cvy[nc]=vAy-vBy; nc+=1
                        cvx[nc]=vAx-pBx; cvy[nc]=vAy-pBy; nc+=1
        md=0.0; trx=0.0; try_=0.0
        found=False
        for k in range(nc):
            vx=cvx[k]; vy=cvy[k]
            if fabs(vx)<TOL and fabs(vy)<TOL: continue
            if haveprev and (vy*prevy+vx*prevx)<0:
                ul=hypot(vx,vy); pl=hypot(prevx,prevy)
                if ul<1e-12 or pl<1e-12: continue
                ux=vx/ul; uy=vy/ul; pux=prevx/pl; puy=prevy/pl
                if fabs(uy*pux-ux*puy)<1e-4: continue
            d=c_slidedist(Ax,Ay,nA,Bx,By,nB,vx,vy)
            v2=vx*vx+vy*vy
            if isnan(d) or d*d>v2: d=sqrt(v2)
            if d>md:
                md=d; trx=vx; try_=vy; found=True
        if not found or fabs(md)<TOL: break
        prevx=trx; prevy=try_; haveprev=True
        v2=trx*trx+try_*try_
        if md*md<v2 and fabs(md*md-v2)>TOL:
            sc=sqrt((md*md)/v2); trx*=sc; try_*=sc
        rx+=trx; ry+=try_
        for i in range(nB): Bx[i]+=trx; By[i]+=try_
        if fabs(rx-sx)<TOL and fabs(ry-sy)<TOL: break
        found=False
        for k in range(len(out)-1):
            if fabs(rx-out[k][0])<TOL and fabs(ry-out[k][1])<TOL: found=True; break
        if found: break
        out.append((rx,ry))
    free(Ax); free(Ay); free(Bx); free(By); free(cvx); free(cvy)
    return out
