
import scipy as sp
from scipy import linalg as spl
from scipy.optimize import minimize
from itertools import groupby
from collections import defaultdict
from gpbo.core import PES
from gpbo.core import ESutils
import DIRECT
from gpbo.core.optutils import silentdirectwrapped as direct
from sklearn import mixture
import logging
import tqdm
import gpbo
from scipy.stats import norm as norms
from scipy import integrate as spi
from gpbo.core import GPdc as GP
logger = logging.getLogger(__name__)
try:
    from matplotlib import pyplot as plt
    from matplotlib import patches
    plots=True
    #plt.style.use('seaborn-paper')
except ImportError:
    plots=False
    plt=None
import os
import time
from copy import deepcopy


try:
    # Python 2
    xrange
except NameError:
    # Python 3, xrange is now named to range
    xrange = range

def always0(optstate,persist,**para):
    return 0,None,dict()
from gpbo.core import GPdc
def prob(G,x,tol=1e-3,dropdims=[]):
    nsam = 10*int(1./tol)+1
    Gr, varG, H, Hvec, varHvec, M, varM = gpbo.core.optutils.gpGH(G,x)
    d=G.D
    vHdraws = GPdc.draw(Hvec.flatten(),varHvec,nsam)
    pvecount = 0
    count = sp.zeros(d)
    count2  = sp.zeros(d)
    for i in xrange(nsam):
        Hdraw = gpbo.core.optutils.Hvec2H(vHdraws[i,:], d)
        g,v = sp.linalg.eigh(Hdraw)
        count+=g>0
        
    logger.debug('eigenvector probs {}'.format((count+1.)/(nsam+2.)))
    return

def drawpartitionmin2(G,S,xm,rm,n):
    #distance to xmin
    xm = sp.array(xm)
    ns,d = S.shape
    #R is distance from xm for each S
    R = sp.empty(ns)
    for i in xrange(ns):
        R[i] = sp.linalg.norm(S[i,:]-xm)
    #O is indicies by distance from xm
    O = sp.argsort(R)
    split = sp.searchsorted(R[O],rm)+1
    S_ = sp.vstack([xm,S[O,:]])
    Z = G.draw_post(S_, [[sp.NaN]] *(ns+1),  n)
    Res = sp.empty([n,5])
    Res[:,1] = Z[:,:split].min(axis=1)
    Res[:,2] = Z[:,split:].min(axis=1)
    Res[:,3] = Z[:,0]
    Res[:,0] = Res[:,1:3].min(axis=1)
    Res[:,4] = Res[:,1:3].argmin(axis=1)

    argminin = Z[:,:split].argmin(axis=1)
    argminmax = argminin.max()
    maxRin = R[O[argminmax-1]]
    #print(str(argminin)+'\n'+str(argminmax)+'\n'+str(maxRin)+' ' +str(rm)+'\n'+str(R[O[argminin]]))
    print('from {} draws {} in rpve with rad {}. Furthest within rpve index{} rad{} '.format(ns,split,rm,argminmax-1, maxRin))
    return Res, maxRin

def globallocalregret(optstate,persist,**para):
    #doublenormdist
    #norprior
    if persist == None:
        persist = defaultdict(list)
        persist['raiseS']=False
        persist['R']=sp.eye(len(para['lb']))
    if optstate.n < para['onlyafter']:
        return 0, persist, dict()
    if persist['flip']:
        return 1, persist, dict()

    logging.info('globallocalregretchooser with {} inflated diagonal'.format(persist['raiseS']))
    if para['rotate']:
        logging.info('rotate\n{}'.format(persist['R']))
    d = len(para['lb'])
    lb = para['lb']
    ub = para['ub']

    #build a GP with slice-samples hypers
    x = sp.vstack(optstate.x).dot(persist['R'].T)
    y = sp.vstack(optstate.y)
    s = sp.vstack([e['s']+10**optstate.condition for e in optstate.ev])
    dx = [e['d'] for e in optstate.ev]
    logger.info('building GP')
    G = PES.makeG(x, y, s, dx, para['kindex'], para['mprior'], para['sprior'], para['nhyp'],prior=para['priorshape'])

    xminr,ymin,ierror = gpbo.core.optutils.twopartopt(lambda x:G.infer_m_post(persist['R'].dot(x.flatten()).reshape([1,d]),[[sp.NaN]])[0,0],para['lb'],para['ub'],para['dpara'],para['lpara'])
    xmin = persist['R'].dot(xminr.flatten()).reshape([1,d])
    #:mxmin,vxmin = [j[0,0] for j in G.infer_diag_post(optstate.x[0],[[sp.NaN]])]
    logger.info('post min at {}(true) {}(rotated) is {}'.format(xminr,xmin,ymin))

    dropdims=[]
    for i in xrange(d):
        if xminr[i]>0.995*(ub[i]-lb[i])+lb[i] or xminr[i]<lb[i]+(1.-0.995)*(ub[i]-lb[i]):
            dropdims.append(i)
            if not sp.allclose(sp.eye(d),persist['R']):
                print('edge isn\'t working with nonzero rotation')
    logger.info('post min in on edge in axes {}'.format(dropdims))
    #get hessian/grad posterior
    #local probmin elipse at post min
    GH = gpbo.core.optutils.gpGH(G,xmin)
    Gr,cG,H,Hvec,varHvec,M,varM = GH

    #est the local regret
    Mdraws = gpbo.core.GPdc.draw(M[0,:],varM,200)
    lrest=0.
    for i in xrange(200):
        sM = Mdraws[i,:]
        sG = sM[:d]
        sH = gpbo.core.optutils.Hvec2H(sM[d:],d)
        sR = 0.5*sG.dot(sp.linalg.solve(sH,sG))
        lrest+= max(0.,sR)
    lrest/=200.
    logger.info('localregretest {}'.format(lrest))

    m = sp.diag(H)
    v = sp.diag(gpbo.core.optutils.Hvec2H(sp.diagonal(varHvec),d))
    logger.debug('H,stH\n{}\n{}'.format(H,sp.sqrt(gpbo.core.optutils.Hvec2H(sp.diagonal(varHvec),d))))
    logger.debug('axisprobs {}'.format(1.-sp.stats.norm.cdf(sp.zeros(d),loc=m,scale=sp.sqrt(v))))
    #step out to check +ve defininteness
    logger.info('checking for +ve definite ball')
    from gpbo.core import debugoutput
    pc = gpbo.core.optutils.probgppve(G,sp.array(xmin),tol=para['pvetol'],dropdims=dropdims)
    logger.info('prob pvedef at xmin {}'.format(pc))

    _ = prob(G,sp.array(xmin),tol=para['pvetol'],dropdims=dropdims)
    if para['rotate']:
        #U,S,V = sp.linalg.svd(H)
        eva,eve = sp.linalg.eigh(H)
        V = eve.T
        persist['R'] = V.dot(persist['R'])
    mask = sp.ones(d)
    for i in dropdims:
        mask[i]=0.
    def PDcondition(x):
        P= gpbo.core.optutils.probgppve(G,sp.array(x)*mask+sp.array(xmin),tol=para['pvetol'],dropdims=dropdims)
        C= P>1-para['pvetol']
        #print(C,P,sp.array(x)*mask)
        return C

    #todo assuming unit radius search region for Rinit=1
    rmax = gpbo.core.optutils.ballradsearch(d,1.,PDcondition,ndirs=para['nlineS'],lineSh=para['lineSh'])

    if gpbo.core.debugoutput['adaptive']:
        import matplotlib
        matplotlib.rcParams['text.usetex']=False
        fig, ax = plt.subplots(nrows=3, ncols=4, figsize=(85, 85))
        xmin=xmin.flatten()
        # plot the current GP
        if d==2:
            #gpbo.core.optutils.gpplot(ax[0,0],ax[0,1],G,para['lb'],para['ub'],ns=60)
            ax[0,0].set_title('GP post mean')
            ax[0,1].set_title('GP post var')
            ax[0,0].plot(xmin[0], xmin[1], 'ro')
            #plot some draws from H
            for i in xrange(4):
                Gm,Gv,Hd = gpbo.core.drawconditionH(*GH)
                try:
                    sp.linalg.cholesky(Hd)
                    gpbo.core.optutils.plotprobstatellipse(Gv,Hd,xmin,ax[1,1],logr=True)
                except sp.linalg.LinAlgError:
                    pass
        if rmax>0:
            ax[1,1].plot([sp.log10(rmax)]*2,[0.,2*sp.pi],'purple')
        else:
            logger.debug('plotting some draws...')
            #draw support points

            xvmaxr,vmax,ierror = gpbo.core.optutils.twopartopt(lambda x:-G.infer_diag_post(persist['R'].dot(x.flatten()),[[sp.NaN]])[1][0,0],para['lb'],para['ub'],para['dpara'],para['lpara'])
            xvmax = persist['R'].dot(xvmaxr.flatten())
            mvmax,vvmax = [j[0,0] for j in G.infer_diag_post(xvmax,[[sp.NaN]])]
            W = sp.vstack([ESutils.draw_support(G, lb, ub, para['support']/2, ESutils.SUPPORT_LAPAPROT, para=20,rotation=persist['R']),ESutils.draw_support(G, lb, ub, para['support']/2, ESutils.SUPPORT_VARREJ, para=vvmax,rotation=persist['R'])])
            nd = 1500
            #draw mins and value of g at xmin as pair
            R, Y, A = ESutils.draw_min_xypairgrad(G, W, nd, xmin)
            #plot support
            if d==2:
                gpbo.core.optutils.plotaslogrtheta(W[:,0],W[:,1],xmin[0],xmin[1],ax[1,1],'b.')
                ax[0,2].plot(W[:,0],W[:,1],'b.')
                #plot mindraws
                gpbo.core.optutils.plotaslogrtheta(R[:,0],R[:,1],xmin[0],xmin[1],ax[1,1],'r.')
                ax[0,2].plot(R[:,0],R[:,1],'r.')
        ax[1,3].text(0,0,'prob +ve at min {}\nR+ve {}'.format(pc,rmax))
    if rmax==0:
        if gpbo.core.debugoutput['adaptive']:
            try:
                fname = 'lotsofplots' + time.strftime('%d_%m_%y_%H:%M:%S') + '.png'
                print('saving as {}'.format(fname))
                fig.savefig(os.path.join(gpbo.core.debugoutput['path'], fname))
            except BaseException as e:
                logger.error(str(e))
            fig.clf()
            plt.close(fig)
            del (fig)
        logger.info('no +ve def region, choosereturns 0')
        return 0,persist,{'reuseH':[k.hyp for k in G.kf],'ppveatx':pc,'rpve':rmax,'R':persist['R']}


    xvmaxr,vmax,ierror = gpbo.core.optutils.twopartopt(lambda x:-G.infer_diag_post(persist['R'].dot(x.flatten()),[[sp.NaN]])[1][0,0],para['lb'],para['ub'],para['dpara'],para['lpara'])
    xvmax = persist['R'].dot(xvmaxr.flatten())
    mvmax,vvmax = [j[0,0] for j in G.infer_diag_post(xvmax,[[sp.NaN]])]
    logger.info('post var max {} at {} with mean {}'.format(vvmax,xvmax,mvmax))
    #draw support points
    W = sp.vstack([ESutils.draw_support(G, lb, ub, para['support']/2, ESutils.SUPPORT_LAPAPROT, para=20,weighted=para['weighted'],rotation=persist['R']),ESutils.draw_support(G, lb, ub, para['support']/2, ESutils.SUPPORT_VARREJ, para=vvmax, rotation=persist['R'])])

    Q, maxRin = drawpartitionmin2(G,W,xmin,rmax,para['draws'])

    logger.info('+ve region radius {} max sample radius {}'.format(rmax, maxRin))
    #pcurves from Q
    def data2cdf(X):
        n = X.size
        C = sp.linspace(1./n,1,n)
        XC = sorted(X)
        return XC,C

    Yin,Cin = data2cdf(Q[:,1])
    normin = sp.stats.norm.fit(Yin)

    Yat,Cat = data2cdf(Q[:,3])
    normat = sp.stats.norm.fit(Yat)

    Yout,Cout = data2cdf(Q[:,2])

    #normal dist with var same as max in gp model and passing through estimated prob of min sample
    ydrawmin=Yout[0]
    cdfymin=Cout[0]
    mu = ydrawmin-sp.sqrt(vvmax*2)*sp.special.erfinv(2*cdfymin-1.)
    logger.info('upper norm at y {} c {} has mu {},var {}'.format(ymin,cdfymin,mu,vvmax))
    logger.info('lower norm at x {} has mu {},var {}'.format(xvmax,mvmax,vvmax))

    #interpolator for cdf
    def splicecdf(y):
        if y<Yout[0]:
            return sp.stats.norm.cdf(y,loc=mu,scale=sp.sqrt(vvmax))
        elif y>=Yout[-1]:
            return 1.-1e-20
        else:
            i=0
            while Yout[i]<y:
                i+=1
            return Cout[i]
        return

    m,std=normin
    logger.debug('inner approx m{} std{}\noutsample stats min{} max{} mean{}'.format(m,std,sp.array(Yout).min(),sp.array(Yout).max(),sp.mean(Yout)))

    racc = 0.
    n=len(Cout)
    #regret from samples after the min
    for i in xrange(1,n):
        racc+= gpbo.core.GPdc.EI(-Yout[i],-m,std)[0,0]/float(n)
    tmp=racc
    #regret from the tail bound
    I,err = spi.quad(lambda y:gpbo.core.GPdc.EI(-y,-m,std)[0,0]*sp.stats.norm.pdf(y,mu,sp.sqrt(vvmax)),-sp.inf,Yout[0])
    racc+=I
    logger.info('outer regret {}  (due to samples: {} due to tail: {}'.format(racc,tmp,racc-tmp))

    #regret lower bound
    #rlow,err = spi.quad(lambda y:gpbo.core.GPdc.EI(-y,-m,v)[0,0]*sp.stats.norm.pdf(y,mvmax,sp.sqrt(vvmax)),-sp.inf,mvmax)
    #regret from samples

    rsam=0.
    for i in xrange(Q.shape[0]):
        rsam+=max(0.,Q[i,1]-Q[i,2])
    rsam/=Q.shape[0]

    #local regret from incumbent from samples
    rloc=0.
    for i in xrange(Q.shape[0]):
        rloc+=max(0.,Q[i,3]-Q[i,1])
    rloc/=Q.shape[0]
    persist['localsampleregret'].append(rloc)
    #set switch to local if condition achieved
    if racc<para['regretswitch']:
        rval=1
        persist['flip']=True
        optstate.startlocal=xmin
    elif maxRin<0.9*rmax:
        rval=2

    else:
        rval=0
        persist['flip']=False
    if gpbo.core.debugoutput['adaptive']:
        if d==2:
            gpbo.core.optutils.plotaslogrtheta(W[:,0],W[:,1],xmin[0],xmin[1],ax[1,1],'b.')
            ax[0,2].plot(W[:,0],W[:,1],'b.')
            #plot mindraws
            R, Y, A = ESutils.draw_min_xypairgrad(G, W, 1500, xmin)
            gpbo.core.optutils.plotaslogrtheta(R[:,0],R[:,1],xmin[0],xmin[1],ax[1,1],'r.')

            ax[0,2].plot(R[:,0],R[:,1],'r.')
        ax[2,2].plot(Q[:,1],Q[:,2],'r.')
        ax[2,2].set_xlabel('inR')
        ax[2,2].set_ylabel('outR')
        ax[2,2].plot([ymin],[ymin],'go')

        ax[2,1].plot(Q[:,1],Q[:,3],'r.')
        ax[2,1].set_xlabel('inR')
        ax[2,1].set_ylabel('atArg')
        ax[2,1].plot([ymin],[ymin],'go')

        def pltcdf(Y,C,ax,col):
            return ax.plot(sp.hstack([[i,i] for i in Y])[1:-1],sp.hstack([[i-C[0],i] for i in C])[1:-1],color=col,label='Sampled CDF')

        pltcdf(Yin,Cin,ax[2,0],'b')
        rin = sp.linspace(Yin[0],Yin[-1],150)
        ax[2,0].plot(rin, [sp.stats.norm.cdf(x,*normin) for x in rin],'k')


        pltcdf(Yat,Cat,ax[2,0],'g')
        rat = sp.linspace(Yat[0],Yat[-1],150)
        ax[2,0].plot(rat, [sp.stats.norm.cdf(x,*normat) for x in rat],'k')
        ax[2,0].set_yscale('logit')


        pltcdf(Yout,Cout,ax[1,0],'r')
        ax[1,0].set_yscale('logit')

        rl = min(Yout)
        ru = max(Yout)
        sup = sp.linspace(rl-0.25*(ru-rl),0.5*(rl+ru),50)
        ax[1,0].plot(sup,sp.stats.norm.cdf(sup,loc=mu,scale=sp.sqrt(vvmax)),'b--',label='Approximate Tail Upper Bound')
        ax[1,0].plot(sup,sp.stats.norm.cdf(sup,loc=mvmax,scale=sp.sqrt(vvmax)),'g--',label='Lower Bound')
        ax[1,0].axvline(ymin)

        if True:
            f2,a2 = plt.subplots(figsize=[8,5])
            pltcdf(Yout,Cout,a2,'r')
            a2.set_yscale('logit')

            a2.plot(sup,sp.stats.norm.cdf(sup,loc=mu,scale=sp.sqrt(vvmax)),color='b',linestyle='--', label='Approx Tail Upper Bound')
            a2.plot(sup,sp.stats.norm.cdf(sup,loc=mvmax,scale=sp.sqrt(vvmax)),color='b',linestyle='-.',label='Lower Bound')
            a2.axvline(ymin,label='Posterior Mean Minimum',color='k',linestyle=':')
            a2.set_ylabel('CDF')
            a2.set_xlabel('y')
            from matplotlib.ticker import NullFormatter
            a2.yaxis.set_minor_formatter(NullFormatter())
            a2.spines['left']._adjust_location()

            a2.legend()
            f2.savefig(os.path.join(debugoutput['path'],'ends.png'))

            plt.close(f2)
            import pickle
            pickle.dump([sup,mu,vvmax,mvmax,ymin,Yout,Cout],open('results/bounddata.p','w'))
        mxo=Yout[-1]
        mno=Yout[0]
        ro = sp.linspace(min(mno-0.05*(mxo-mno),ymin),mxo+0.05*(mxo-mno),200)


        ax[1,2].text(0,0.34, 'regretg sample      {}'.format(rsam))
        ax[1,2].text(0,0.24, 'regretg tailest     {}'.format(racc))
        #ax[1,2].text(0,0.18, 'regretg binormest   {}'.format(rbin))
        #ax[1,2].text(0,0.08, 'regretg lowerb      {} '.format(rlow))

        ax[1,2].text(0,0.5,'maxRin  {} / {}'.format(maxRin,rmax))
        ax[1,2].text(0,0.6,'mode  {}'.format(rval))

        ax[1,2].text(0,0.74,'localr sample     {}'.format(rloc))
        ax[1,2].text(0,0.8, 'localr Taylor est {} '.format(lrest))
        persist['Rexists'].append(optstate.n)
        persist['sampleregret'].append(rsam)
        persist['expectedregret'].append(racc)
        #persist['expectedRbinorm'].append(rbin)
        persist['localrsam'].append(rloc)
        #persist['regretlower'].append(rlow)
        persist['localrest'].append(lrest)
        ax[0,3].plot(persist['Rexists'],persist['localrest'],'k')
        #ax[0,3].plot(persist['Rexists'],persist['expectedRbinorm'],'purple')
        ax[0,3].plot(persist['Rexists'],persist['sampleregret'],'b')
        ax[0,3].plot(persist['Rexists'],persist['expectedregret'],'g')
        ax[0,3].plot(persist['Rexists'],persist['localrsam'],'r')
        #ax[0,3].plot(persist['Rexists'],persist['regretlower'],'purple')
        ax[0,3].set_yscale('log')


        #ax[2,3].plot(K[:,0],K[:,1],'b.')
        try:
            fname = 'lotsofplots' + time.strftime('%d_%m_%y_%H:%M:%S') + '.png'
            print('saving as {}'.format(fname))
            fig.savefig(os.path.join(gpbo.core.debugoutput['path'], fname))
        except BaseException as e:
            logger.error(str(e))
        fig.clf()
        plt.close(fig)
        del (fig)

    #if a cheat objective as available see how we would do on starting a local opt now
    if 'cheatf' in list(para.keys()):
        try:
            C = sp.linalg.cholesky(H)
        except:
            logger.info('not +ve definite at posterior min')
            C=sp.linalg.cholesky(sp.eye(H.shape[0]))
        print('C {} \nxmin {}\nC.T.xmin{}'.format(C,xmin,C.T.dot(xmin)))
        def fn2(x):
            print(x,para['cheatf'](sp.linalg.solve(C.T,x),**{'s':0.,'d':[sp.NaN]})[0])
            return para['cheatf'](sp.linalg.solve(C.T,x),**{'s':0.,'d':[sp.NaN]})[0]
        R=minimize(fn2,C.T.dot(xmin),method='bfgs')
        logger.warn('cheat testopt result with precondition {}:\n{}'.format(H,R))

    return rval,persist,{'start':xminr.flatten(),'H':H,'reuseH':[k.hyp for k in G.kf],'offsetEI':m,'ppveatx':pc,'rpve':rmax,'log10GRest':sp.log10(racc)}


def alternate(optstate,persist,**para):
    return optstate.n%2,None,dict()


def aftern(optstate,persist,**para):
    if optstate.n>para['n']:
        return 1,None,{'start':[0.,0.]}
    else:
        return 0,None,dict()


