# Power of a paired comparison between two executor x model arms on the same task set.
# Assumptions: per-task difficulty ~ Normal(0, 1.5) on the logit scale, a constant logit
# shift between arms, k repetitions per task, t-test on per-task mean differences.
# Run: uv run --with numpy python -I docs/assets/power_sim.py [--ni]
# --ni prints the mean half-width of the 95 % CI of the paired pass@1 difference between two
# equal arms, used to pick the non-inferiority margin (01-metrics §3).

import sys
import numpy as np
rng=np.random.default_rng(0)
def power(n,k,delta_logit,sims=3000,base=0.0,sd=1.5):
    hits=0
    for _ in range(sims):
        z=rng.normal(base,sd,n)              # task difficulty (logit)
        pa=1/(1+np.exp(-z)); pb=1/(1+np.exp(-(z+delta_logit)))
        a=rng.binomial(k,pa)/k; b=rng.binomial(k,pb)/k
        d=b-a
        # paired sign-flip permutation test approx via t-test on per-task diffs
        if d.std(ddof=1)==0: continue
        t=d.mean()/(d.std(ddof=1)/np.sqrt(n))
        crit = 2.045 if n == 30 else 1.98  # two-sided 5 %, df = n - 1
        if abs(t) > crit: hits += 1
    return hits/sims
def pp_gap(delta_logit,base=0.0,sd=1.5,m=200000):
    z=rng.normal(base,sd,m); return (1/(1+np.exp(-(z+delta_logit)))-1/(1+np.exp(-z))).mean()
def ni_halfwidth(n,k,sims=4000,base=0.0,sd=1.5):
    w=[]
    for _ in range(sims):
        p=1/(1+np.exp(-rng.normal(base,sd,n)))
        d=rng.binomial(k,p)/k-rng.binomial(k,p)/k
        w.append(1.96*d.std(ddof=1)/np.sqrt(n))
    return float(np.mean(w))
if "--ni" in sys.argv:
  for n in (30,50,80,150):
    print(f"n={n} " + " ".join(f"k={k} halfwidth={ni_halfwidth(n,k)*100:.1f}pp" for k in (3,5)))
else:
  for n in (30,50,100):
    for k in (1,3,5):
      for dl in (0.5,0.75,1.0,1.5):
        print(f"n={n} k={k} gap={pp_gap(dl)*100:.1f}pp power={power(n,k,dl,1500):.2f}")
