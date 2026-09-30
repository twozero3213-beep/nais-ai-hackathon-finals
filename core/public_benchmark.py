"""Public-research benchmark using Horst, Hill & Gorman (2022), The R Journal.

case32 PUBLIC BENCHMARK
WHY: synthetic blind tests find engineering bugs but cannot establish real-research reproduction.
This benchmark uses the public Palmer Penguins curated dataset and claims explicitly reported in
RJ-2022-020. It is intentionally transparent: it tests deterministic claims that the public CSV can
reproduce, and does NOT claim to reproduce every analysis or the authors' full R environment.
"""
from __future__ import annotations
from pathlib import Path
import hashlib, json
import numpy as np
import pandas as pd
from .paths import PROJECT_ROOT

ARTICLE_URL="https://journal.r-project.org/articles/RJ-2022-020/"
ARTICLE_PDF_URL="https://journal.r-project.org/articles/RJ-2022-020/RJ-2022-020.pdf"
DATA_URL="https://github.com/allisonhorst/palmerpenguins/blob/main/inst/extdata/penguins.csv"
DATA_PATH=PROJECT_ROOT/"data"/"penguins_public_benchmark.csv"
CITATION="Horst AM, Hill AP, Gorman KB (2022). Palmer Archipelago Penguins Data in the palmerpenguins R Package - An Alternative to Anderson's Irises. The R Journal 14(1):244-254. DOI:10.32614/RJ-2022-020."

def file_sha256(path=DATA_PATH):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _row(claim_id,claim,reported,recomputed,passed,detail):
    return {"claim_id":claim_id,"claim":claim,"reported":reported,"recomputed":recomputed,"passed":bool(passed),"detail":detail}

def run_public_benchmark(path=DATA_PATH):
    df=pd.read_csv(path)
    out=[]
    out.append(_row("PB-01","penguins dimensions are 8 x 344","8 x 344",f"{df.shape[1]} x {df.shape[0]}",df.shape==(344,8),"R Journal Table 1 / data structure"))
    missing=int(df.isna().sum().sum()); total=int(df.shape[0]*df.shape[1]); pct=100*missing/total
    out.append(_row("PB-02","penguins contains 19 missing values (0.7%)","19 / 2752 (0.7%)",f"{missing} / {total} ({pct:.2f}%)",missing==19 and total==2752 and round(pct,1)==0.7,"R Journal Table 1 and text"))
    expected={"Adelie":{"female":73,"male":73,"NA":6},"Chinstrap":{"female":34,"male":34,"NA":0},"Gentoo":{"female":58,"male":61,"NA":5}}
    actual={}
    for species,g in df.groupby("species",dropna=False):
        vc=g["sex"].value_counts(dropna=False);actual[str(species)]={"female":int(vc.get("female",0)),"male":int(vc.get("male",0)),"NA":int(g["sex"].isna().sum())}
    out.append(_row("PB-03","species-by-sex sample sizes match Table 2",expected,actual,actual==expected,"R Journal Table 2"))
    overall=float(df[["bill_length_mm","bill_depth_mm"]].corr().iloc[0,1])
    out.append(_row("PB-04","bill length and depth are negatively correlated overall","negative",overall,overall<0,"R Journal Simpson's Paradox text / Figure 5"))
    within={s:float(g[["bill_length_mm","bill_depth_mm"]].corr().iloc[0,1]) for s,g in df.groupby("species")}
    out.append(_row("PB-05","bill length and depth are positively correlated within each species","all positive",within,all(v>0 for v in within.values()),"R Journal Simpson's Paradox text / Figure 5"))
    cols=["flipper_length_mm","body_mass_g","bill_length_mm","bill_depth_mm"]
    X=df[cols].dropna().to_numpy(float);X=(X-X.mean(0))/X.std(0,ddof=1)
    eig=np.linalg.eigvalsh(np.cov(X,rowvar=False))[::-1];pc12=float(eig[:2].sum()/eig.sum()*100)
    out.append(_row("PB-06","first two PCA components capture 88.15% of total variance","88.15%",pc12,abs(pc12-88.15)<=0.02,"R Journal PCA section / Figure 6"))
    return {"article_url":ARTICLE_URL,"article_pdf_url":ARTICLE_PDF_URL,"data_url":DATA_URL,"citation":CITATION,"dataset_sha256":file_sha256(path),"claims":out,"passed":sum(x["passed"] for x in out),"total":len(out)}
