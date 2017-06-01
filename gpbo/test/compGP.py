import numpy as np
from gpbo.core import GPdc
from gpbo.core import flow
from matplotlib import pyplot as plt
import time
import random

t0=time.time()
N = 14
x = np.sort(np.random.rand(N,1)*2.-1,axis=0)
X = np.hstack([x])
D = [[np.NaN]]*N
S = np.ones([N,1])*0.25
#print X
y= (np.exp(-x)+np.sin(4*x))**2+np.random.randn(N,1)*0.5
dy = 2*(np.exp(-x)+np.sin(4*x))*(-np.exp(-x)+4*np.cos(4*x))+np.random.randn(N,1)*0.5

d2y = (2*(-np.exp(-x) + 4*np.cos(4*x))**2 + 2*(np.exp(-x) - 16*np.sin(4*x))* (np.exp(-x) + np.sin(4*x)))+np.random.randn(N,1)*0.5

Y = np.copy(y)
for i in range(N//2):
    j = random.randint(0,N-1)
    Y[j]=dy[j]
    D[j]=[0]
    j = random.randint(0,N-1)
    Y[j]=d2y[j]
    D[j]=[0,0]


def plot(m,a):
    xp = np.array([np.linspace(-1.1, 1.1, 200)]).T

    for i in range(X.shape[0]):
        if np.isnan(D[i][0]):
            a[0].plot(X[i,0], Y[i], 'r.')
        elif D[i]==[0]:
            a[1].plot(X[i,0], Y[i], 'r.')
        elif D[i]==[0,0]:
            a[2].plot(X[i,0], Y[i], 'r.')

    mean, var = m.infer_diag_post(xp,[[np.NaN]]*200)
    a[0].plot(xp, mean.flatten(), 'b')
    a[0].fill_between(xp[:,0], mean.flatten() - 2*np.sqrt(var.flatten()), mean.flatten() + 2*np.sqrt(var.flatten()), color='blue', alpha=0.2)
    a[0].twinx().semilogy(xp[:,0],var.flatten(),'purple')


    mean, var = m.infer_diag_post(xp,[[0]]*200)
    a[1].plot(xp, mean.flatten(), 'b')
    a[1].fill_between(xp[:,0], mean.flatten() - 2*np.sqrt(var.flatten()), mean.flatten() + 2*np.sqrt(var.flatten()), color='blue', alpha=0.2)
    a[1].twinx().semilogy(xp[:,0],var.flatten(),'purple')

    mean, var = m.infer_diag_post(xp,[[0,0]]*200)
    a[2].plot(xp, mean.flatten(), 'b')
    a[2].fill_between(xp[:,0], mean.flatten() - 2*np.sqrt(var.flatten()), mean.flatten() + 2*np.sqrt(var.flatten()), color='blue', alpha=0.2)
    a[2].twinx().semilogy(xp[:,0],var.flatten(),'purple')

    y= 1*(np.exp(-xp)+np.sin(4*xp))**2
    dy = 2*(np.exp(-xp)+np.sin(4*xp))*(-np.exp(-xp)+4*np.cos(4*xp))
    d2y = 1*(2*(-np.exp(-xp) + 4*np.cos(4*xp))**2 + 2*(np.exp(-xp) - 16*np.sin(4*xp))* (np.exp(-xp) + np.sin(4*xp)))
    a[0].plot(xp,y,'g--')
    a[1].plot(xp,dy,'g--')
    a[2].plot(xp,d2y,'g--')
kp = np.array([[2.,0.4],[1.5,0.3],[2.1,0.35]])
k = [GPdc.kernel(GPdc.SQUEXP,1,kp[i,:]) for i in range(kp.shape[0])]
kf = [flow.kernel(flow.SQUEXP,1,kp[i,:]) for i in range(kp.shape[0])]

m = GPdc.GPcore(X,Y,S,D,k)
mf = flow.GPcore(X,Y,S,D,kf)

#f,a = plt.subplots(nrows=3,ncols=2,figsize=(9, 6))
#plot(m,a[:,0])
#plot(mf,a[:,1])

M=4

x = np.sort(np.random.rand(M,1)*2.-1,axis=0)
Di = [[[np.NaN],[0],[0,0]][j] for j in np.random.random_integers(0,2,M)]

mean = m.infer_m(x,Di)
fmean = mf.infer_m(x,Di)
print('m: {}'.format(np.allclose(mean,fmean,rtol=1e-3) ))

mean = m.infer_m_post(x,Di)
fmean = mf.infer_m_post(x,Di)
print('m_post: {}'.format(np.allclose(mean,fmean,rtol=1e-3) ))

mean,var = m.infer_diag(x,Di)
fmean,fvar = mf.infer_diag(x,Di)
print('diag: {}'.format(np.allclose(mean,fmean,rtol=1e-3) and np.allclose(var,fvar,rtol=1e-3)))

mean,var = m.infer_diag_post(x,Di)
fmean,fvar = mf.infer_diag_post(x,Di)
print('diag_post: {}'.format(np.allclose(mean,fmean,rtol=1e-3) and np.allclose(var,fvar,rtol=1e-3)))

mean,var = m.infer_full(x,Di)
fmean,fvar = mf.infer_full(x,Di)
print('full: {}'.format(np.allclose(mean,fmean,rtol=1e-3) and np.allclose(var,fvar,rtol=1e-3)))

mean,var = m.infer_full_post(x,Di)
fmean,fvar = mf.infer_full_post(x,Di)
print('full_post: {}'.format(np.allclose(mean,fmean,rtol=1e-3) and np.allclose(var,fvar,rtol=1e-3)))

llk = [m.llk(),mf.llk()]
print('llk: {}'.format(np.allclose(llk[0],llk[1])))

#---------------------------------
#optimize a single hyp set
#MLE = GPdc.searchMLEhyp(X,Y,S,D, np.array([-2.,-2.]), np.array([2.,2.]), GPdc.SQUEXP)
#print(MLE[0]**2,MLE[1])
MLE = flow.searchMLEhyp(X,Y,S,D, np.array([-2.,-2.]), np.array([2.,2.]), GPdc.SQUEXP)

#MAP = GPdc.searchMAPhyp(X,Y,S,D, np.array([0.,0.]), np.array([2.,2.]), GPdc.SQUEXP)
#print(MAP[0]**2,MAP[1])
MAP = flow.searchMAPhyp(X,Y,S,D, np.array([0.,0.]), np.array([20.,20.]), GPdc.SQUEXP)