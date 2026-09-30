"""case95 plain-language research desk; static HTML only, no remote/user HTML."""
import streamlit as st


# [작성: UX 총괄] 2026-09-29 case95 / 전용홈 여백·계층·모바일 / 기존 전문가 화면과 HTML 입력 경계 유지.
def render_home_header():
    st.markdown('\n'.join(line.lstrip() for line in '''<style>
    .nais-hero {background:linear-gradient(115deg,#102a43 0%,#174b65 64%,#276867 100%);color:#fff;
      padding:2rem 2.2rem;border-radius:22px;margin:0 0 1.5rem;box-shadow:0 12px 32px #102a4314}
    .nais-hero .eyebrow{font-size:.8rem;letter-spacing:.16em;color:#a9e3db;font-weight:700}
    .nais-hero h1{font-size:clamp(1.65rem,3vw,2.7rem);line-height:1.3;color:#fff;margin:.55rem 0 .65rem;padding:0}
    .nais-hero p{font-size:1.02rem;max-width:50rem;color:#e2edf4;line-height:1.8;margin:0}
    .nais-steps{display:flex;flex-wrap:wrap;gap:.65rem;margin-top:1.1rem}
    .nais-steps span{border:1px solid #91cbd350;border-radius:99px;padding:.35rem .8rem;background:#ffffff10;color:#fff;font-size:.85rem}
    [data-testid="stRadio"] div[role="radiogroup"]{gap:.65rem}
    [data-testid="stRadio"] label{padding:.35rem .4rem;line-height:1.65}
    [data-testid="stVerticalBlockBorderWrapper"]{border-radius:16px!important}
    @media(max-width:640px){.nais-hero{padding:1.25rem;border-radius:16px}.nais-steps{gap:.4rem}.nais-steps span{font-size:.78rem}}
    </style><section class="nais-hero"><div class="eyebrow">NAIS · RESEARCH DESK</div>
    <h1>연구를 발견하고,<br>그 근거까지 확인하세요.</h1>
    <p>새 논문을 둘러보고, 궁금한 내용을 과제로 남기세요.<br>출처와 계산으로 확인한 내용, 아직 모르는 내용을 나란히 보여드립니다.</p>
    <div class="nais-steps"><span>01 관심 연구 찾기</span><span>02 근거 확인하기</span><span>03 결과 가져가기</span></div></section>'''.splitlines()),unsafe_allow_html=True)
