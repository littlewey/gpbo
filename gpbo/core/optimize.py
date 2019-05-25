# To change this license header, choose License Headers in Project Properties.
# To change this template file, choose Tools | Templates
# and open the template in the editor.
import pickle
import scipy as sp
import numpy as np
import os
import time
import logging
import copy
import pandas as pd
import gpbo
import re
import traceback
logger = logging.getLogger(__name__)


try:
    # Python 2
    xrange
except NameError:
    # Python 3, xrange is now named to range
    xrange = range


class optstate:
    def __init__(self):
        self.x = []
        self.ev = []
        self.y = []
        self.c = []
        self.C = 0
        self.n = 0
        self.Cfull=0.
        self.aqtime=[]
        self.aux=None
        self.localdone=False
        self.startlocal= None
        self.remaining = sp.Inf
        self.condition = -999.
        self.conditionV = 0.
        return
    
    def update(self,x,ev,y,c,taq):
        self.x.append(x)
        self.ev.append(copy.copy(ev))
        self.y.append(y)
        self.c.append(c)
        self.C +=c
        self.Cfull+=c+taq
        if sp.isnan(ev['d']):
            self.n+=1
        self.aqtime.append(taq)
        return 


class optimizer:
    def __init__(self,dirpath,name,aqpara,aqfn,stoppara,stopfn,reccpara,reccfn,ojf,ojfchar,choosefn,choosepara,initdata=False):
        self.dirpath = dirpath
        self.name = name
        self.setaq(aqpara,aqfn)
        self.setstopcon(stoppara,stopfn)
        self.setojf(ojf)
        self.setrecc(reccpara,reccfn)
        self.setchoose(choosepara,choosefn)
        self.ojfchar = ojfchar
        self.dx = ojfchar['dx']
        self.dev = ojfchar['dev']
        if initdata:
            self.state=pickle.load(open(initdata))[0]
            print('init with \n{} \n{}'.format(self.state.x,self.state.y))
        else:
            self.state=optstate()
        return
    
    def setaq(self,aqpara,aqfn):
        self.aqfn = aqfn
        self.aqpara = aqpara
        self.aqpersist = [None]*len(aqfn)
        return
    
    def setrecc(self,reccpara,reccfn):
        self.reccpara = reccpara
        self.reccfn = reccfn
        self.reccpersist = [None]*len(reccfn)
        return

    def setchoose(self,choosepara,choosefn):
        self.choosepara = choosepara
        self.choosefn =choosefn
        self.choosepersist = None
        return
    def setstopcon(self,stoppara,stopfn):
        self.stoppara = stoppara
        self.stopfn=stopfn
        return
    
    def setojf(self,ojf):
        self.ojf = ojf
        return
    
    def run(self):
        logger.info('startopt:')
        #print( self.aqpara)
        self.stoppara['t0']=time.clock()
        lf = open(os.path.join(self.dirpath,self.name),'w')
        lf.write(''.join(['n, ']+['x'+str(i)+', ' for i in xrange(self.dx)]+[i+', ' for i in list(self.aqpara[0]['ev'].keys())]+['y, c, ']+['rx'+str(i)+', ' for i in xrange(self.dx)]+['truey at xrecc, taq, tev, trc, realtime, condition, aqauxdata'])+'\n')
#        self.state = optstate()
        stepn=self.state.n
        checky=sp.NaN
        rxlast=[sp.NaN]*self.dx
        while not self.stopfn(self.state,**self.stoppara):
            stepn+=1
            #print self.choosepara
            #print self.choosefn

            logger.info("---------------------\nstep {}:".format(stepn))

            t0 = time.clock()
            mode,self.choosepersist,chooseaux = wrap(self.choosefn,self.state,self.choosepersist,**self.choosepara)
            self.aqpara[mode]['choosereturn']=chooseaux
            x,ev,self.aqpersist[mode],aqaux = wrap(self.aqfn[mode],self.state,self.aqpersist[mode],**self.aqpara[mode])
            t1 = time.clock()
            self.state.aux = aqaux
            logger.info("AQ returned {} : {}    aqtime: {}\nevaluate:".format(x,ev,t1-t0))
            if not self.ojfchar['batchgrad']:

                y,c,ojaux  = self.ojf(x,**ev)
                t2 = time.clock()
                logger.info("EV returned {} : {}     evaltime: {}".format(y,c,t2-t1))
            else:
                F,c,ojaux  = self.ojf(x,**ev)
                t2 = time.clock()
                logger.info("EV returned {} : {}     evaltime: {}".format(F,c,t2-t1))
                y = F[0]
                for k in xrange(len(F)-1):
                    ev_ = copy.copy(ev)
                    ev_['d'] = [k]
                    df = F[k+1]
                    self.state.update(x,ev_,df,c,t1-t0)
                    taildata0 = ','.join([str(k)+' '+sanitize(str(aqaux[k])) for k in list(aqaux.keys())])
                    taildata1 = ','.join([str(k)+' '+sanitize(str(aqaux[k])) for k in list(chooseaux.keys())])
                    logstr = ''.join([str(stepn)+', ']+[str(xi)+', ' for xi in x]+[str(evi[1])+', ' for evi in list(ev_.items())]+[str(df)+', ']+[str(c)+', ']+[str(ri)+', ' for ri in rxlast]+[str(checky)+',']+[str(i)+', ' for i in [0.,0.,0.]]+[time.strftime('%H:%M:%S  %d-%m-%y')])+',{},'.format(self.state.conditionV)+taildata0+taildata1+'\n'
                    lf.write(logstr)

            self.state.update(x,ev,y,c,t1-t0)

            t2 = time.clock()
            rx,self.reccpersist[mode],reaux = wrap(self.reccfn[mode],self.state,self.reccpersist[mode],**self.reccpara[mode])
            t3 = time.clock()

            if self.reccpara[mode]['check']:
                #print(rx,rxlast)
                if list(rx)==rxlast:
                    print('reusing check')
                    checky, checkc, checkojaux = checkylast,checkclast,checkojauxlast
                else:
                    print('checking reccomendation:')
                    checkpara=copy.copy(self.aqpara[mode]['ev'])
                    checkpara['s']=1e-99
                    checkpara['cheattrue']=True
                    checky,checkc,checkojaux  = self.ojf(rx,**checkpara)
                    if self.ojfchar['batchgrad']:
                        checky = checky[0]
                    checkylast, checkclast, checkojauxlast = checky,checkc,checkojaux
                    #logger.info("checkout {} : {} : {}".format(checky,checkc,checkojaux))
            else:
                checky=sp.NaN
            rxlast=list(rx)
            logger.info("RC returned {}     recctime: {}\n".format(rx,t3-t2))
            aqaux['host'] = os.uname()[1]

            taildata0 = ','.join([str(k)+' '+sanitize(str(aqaux[k])) for k in list(aqaux.keys())])
            taildata1 = ','.join([str(k)+' '+sanitize(str(chooseaux[k])) for k in list(chooseaux.keys())])
            logstr = ''.join([str(stepn)+', ']+[str(xi)+', ' for xi in x]+[str(evi[1])+', ' for evi in list(ev.items())]+[str(y)+', ']+[str(c)+', ']+[str(ri)+', ' for ri in rx]+[str(checky)+',']+[str(i)+', ' for i in [t1-t0,t2-t1,t3-t2]]+[time.strftime('%H:%M:%S  %d-%m-%y')])+',{},'.format(self.state.conditionV)+taildata0 + taildata1+'\n'
            lf.write(logstr)
            lf.flush()
            if gpbo.core.debugoutput['logstate']:
                pickle.dump(self.state,open(os.path.join(gpbo.core.debugoutput['path'],'{}.p'.format(self.state.n)),'wb'))
        #import pickle
        #obj = [self.reccpersist, self.aqpersist]
        #pickle.dump(obj, open('dbout/persists.p', 'wb'))
        logger.info('endopt')

        return rx,reaux
def sanitize(s):
    s0 = re.sub(r","," ",s)
    s1 = re.sub(r"\n", ";", s0)
    s2 = re.sub(r"\r", ";", s1)
    s3 = re.sub(r"(\d+\.\d\d)\d+", r"\1", s2)
    return s3
def norlocalstopfn(optstate,**para):
    return nstopfn(optstate,**para) or localstopfn(optstate,**para)



def nstopfn(optstate,**para):
    return optstate.n >= para['nmax']

def EIstopfn(optstate,**para):
    try:
        logger.info('EI at X was: {} minlimit {}'.format(optstate.aux['EImax'],para['EImin']))
        return optstate.aux['EImax'] <= para['EImin']
    except:
        return False

def EIorNstopfn(optstate, **para):
    return nstopfn(optstate, **para) or EIstopfn(optstate, **para)

def PIorNstopfn(optstate, **para):
    return nstopfn(optstate, **para) or PIstopfn(optstate, **para)

def AQorNstopfn(optstate, **para):
    return nstopfn(optstate, **para) or AQstopfn(optstate, **para)

def PIstopfn(optstate,**para):
    try:
        logger.info('PI at X was: {} minlimit {}'.format(optstate.aux['PIatX'],para['PImin']))
        return optstate.aux['PIatX'] <= para['PImin']
    except:
        return False

def AQstopfn(optstate,**para):
    try:
        logger.info('AQ at X was: {} minlimit {}'.format(optstate.aux['AQvalue'],para['AQmin']))
        return optstate.aux['AQvalue'] <= para['AQmin']
    except:
        return False
def dxminstopfn(optstate,**para):
    if optstate.n<2:
        return False
    dx = sp.linalg.norm(sp.array(optstate.x[-1])-sp.array(optstate.x[-2]))
    logger.critical(str(optstate.aux))
    logger.info('dx between steps was: {} minlimit {}'.format(dx,para['dxmin']))
    return dx<para['dxmin']

def localstopfn(optstate,**para):
    return optstate.localdone

def cstopfn(optstate,cmax = 1,includeaq=False):
    if not includeaq:
        logger.info('Used {} of {} evaluation budget.'.format(optstate.C,cmax))
        return optstate.C >= cmax
    else:
        logger.info('Used {} of {} evaluation budget.'.format(optstate.Cfull, cmax))
        return optstate.Cfull >= cmax

def totaltstopfn(optstate,**para):
    tused = sum(optstate.aqtime)+optstate.C

    if tused>=para['tmax']:
        logger.info('Time limit reached')
        return True
    else:
        hu=int(tused)/3600
        mu=(int(tused)%3600)/60
        su=int(tused)%60
        ht=int(para['tmax'])/3600
        mt=(int(para['tmax'])%3600)/60
        st=int(para['tmax'])%60
        logger.info('Used {}h {}m {}s of {}h {}m {}s budget \n of which {} acquisition {} evaluation'.format(hu,mu,su,ht,mt,st,(tused-optstate.C)/(1e-9+tused),optstate.C/(tused+1e-9)))
        optstate.remaining = para['tmax'] - tused
        return False

def totalTorNstopfn(optstate, **para):
    return nstopfn(optstate, **para) or totaltstopfn(optstate, **para)

def wrap(fn,optstate,persist,**para):
    if gpbo.core.debugoutput['forceNoiseFloor']:
        optstate.condition = gpbo.core.debugoutput['forceNoiseFloor']
        optstate.conditionV = 10**gpbo.core.debugoutput['forceNoiseFloor']

    try:
        if optstate.condition>-20:
            logger.info('using raised noise floor {} in {}'.format(optstate.condition,fn))
        return fn(optstate,persist,**para)
    except gpbo.core.GPdc.GPdcError as e:
        traceback.print_exc()
        optstate.condition=max(optstate.condition+1.,-19.)
        optstate.conditionV=10**optstate.condition
        logger.error('numerical error in {} fn Raising noise to {}\n\n {}'.format(str(fn),optstate.condition,e))
        return wrap(fn,optstate,persist,**para)

    except np.linalg.linalg.LinAlgError as e:
        traceback.print_exc()
        optstate.condition=max(optstate.condition+1.,-19.)
        optstate.conditionV=10**optstate.condition
        logger.error('numerical error in {} fn Raising noise to {}\n\n {}'.format(str(fn),optstate.condition,e))
        return wrap(fn,optstate,persist,**para)
    except ZeroDivisionError as e:
        traceback.print_exc()
        optstate.condition=max(optstate.condition+1.,-19.)
        optstate.conditionV=10**optstate.condition
        logger.error('numerical error in {} fn Raising noise to {}\n\n {}'.format(str(fn),optstate.condition,e))
        return wrap(fn,optstate,persist,**para)
def search(optconfig,initdata=False):
    if not hasattr(optconfig,'fname'):
        optconfig.fname='traces.csv'
    multi=False
    if hasattr(optconfig,'multimode'):
        if optconfig.multimode:
            multi=True
    if not 'batchgrad' in list(optconfig.ojfchar.keys()):
        optconfig.ojfchar['batchgrad'] = False
    if not multi:
        O = optimizer(optconfig.path, optconfig.fname, [optconfig.aqpara], [optconfig.aqfn], optconfig.stoppara,
                                     optconfig.stopfn, [optconfig.reccpara], [optconfig.reccfn], optconfig.ojf,
                                     optconfig.ojfchar,gpbo.core.choosers.always0,dict(),initdata=initdata)
    else:
        O = optimizer(optconfig.path, optconfig.fname, optconfig.aqpara, optconfig.aqfn, optconfig.stoppara,
                                     optconfig.stopfn, optconfig.reccpara, optconfig.reccfn, optconfig.ojf,
                                     optconfig.ojfchar,optconfig.chooser,optconfig.choosepara,initdata=initdata)

    return O.run()



def readoptdata(fname,includetaq=False):
    df = pd.DataFrame()
    #with open(fname, 'r') as f:
    #    for line in f:
    #        df = pd.concat([df, pd.DataFrame([tuple(line.strip().split(','))])], ignore_index=True)
    #print(df.head())
    names = (open(fname).readline().strip('\n')+''.join([',q{}'.format(i) for i in xrange(18)])).replace(' ','')
    df = pd.read_csv(fname,names=names.split(','),skiprows=1)
    #print(df2.head())
    #print(df.keys())
    #for i in xrange(df.shape[1]):
    #    if not isinstance(df[i][0], str):
    #        df[i][0] = 'augdata{}'.format(j)
     #       j += 1
     #   else:
     #      df[i][0] = df[i][0].replace(' ', '')
    #df.columns = df.iloc[0]
    #df.drop(df.index[[0]], inplace=True)
    #df.reset_index(inplace=True)
    #print(df.head())
    l = len(df['c'])
    df['cacc'] = pd.Series(sp.empty(l), index=df.index)
    df['index'] = pd.Series(list(range(l)), index=df.index)
    df['accE'] = pd.Series(sp.empty(l), index=df.index)
    df['accEA'] = pd.Series(sp.empty(l), index=df.index)
    for c in df.columns:
        try:
            df[c] = df[c].astype(float)  #
        except ValueError:
            pass


    #df['accEA'][0] = df.loc[0, ('c')]+df.loc[0, ('taq')]
    df.loc[0,('accEA')] = df.loc[0, ('c')]+df.loc[0, ('taq')]
    for i in xrange(1, l):
        df.loc[i,('accEA')] = df.loc[i - 1, 'accEA'] + df.loc[i, 'c']+df.loc[i, ('taq')]

    df.loc[0,('accE')] = df.loc[0, ('c')]
    for i in xrange(1, l):
        df.loc[i,('accE')] = df.loc[i - 1, 'accE'] + df.loc[i, 'c']


    if includetaq:
        df['cacc']=df['accEA']
    else:
        df['cacc']=df['accE']

    return df
