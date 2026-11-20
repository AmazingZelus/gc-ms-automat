"""Simulated "ugly" peaks for the documentation (doublet, hump, tailing peak).

Run from the repository root:  python tools/doc_examples/make_data.py
Writes build/doc/cdf/*.CDF and prints measured / true area for each integration setting.
"""
import os
os.makedirs("build/doc/cdf", exist_ok=True)
import sys; sys.path[:0]=['app','tests']
import numpy as np, json
from synthetic import *
from gcms_automat.analysis.cdf import write_cdf
from gcms_automat.analysis.table import Analysis
from gcms_automat.analysis.params import AnalysisParams
def save(run):
    dense=run.spectra.toarray(); scans=[]
    for row in dense:
        nz=np.flatnonzero(row); scans.append((run.mz_min+nz,row[nz]))
    write_cdf(f"build/doc/cdf/{run.name}.CDF", run.rt_min, scans)
hump=Compound({300:100})
S={
 "dvojhrb":   [(A,5.0,8e4,0.025),(B,5.075,5e4,0.025)],
 "hrbol":     [(hump,5.0,6000,0.35),(B,4.85,4000,0.02),(C,5.2,3000,0.02)],
 "chvost":    [(B,5.0,1e6,0.02,0.06),(A,5.2,5e4,0.02)],
 "dvojhrb_na_hrbolu": [(hump,5.0,6000,0.35),(A,5.0,6000,0.022),(B,5.065,4000,0.022)],
}
truth={}
for name,peaks in S.items():
    run=make_run(name,peaks,minutes=10,baseline=3000,noise=30,seed=7); save(run)
    truth[name]=[(rt, gaussian_area(h,s,c)) for c,rt,h,s,*_ in peaks if c is not hump]
    for label,kw in [("auto",{}),("drop",{"integration_baseline":"drop"}),("chord",{"integration_baseline":"chord"}),("slope1",{"window_end_slope_pct":1})]:
        a=Analysis([run],[],AnalysisParams(**kw))
        res=[]
        for rt,true in truth[name]:
            r=[r for r in a.rows if abs(r.rt-rt)<0.03]
            res.append(round(r[0].cells[name].area/true,2) if r else None)
        print(name,label,res)
json.dump(truth,open('build/doc/truth.json','w'))
