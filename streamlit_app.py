import io, datetime, re
import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO

st.set_page_config(page_title="iUSE Zillow Matcher", layout="wide")
st.title("iUSE Zillow Matcher (Manual, 3 buttons)")

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

try:
    from serpapi import GoogleSearch
    SERPAPI_AVAILABLE = True
except Exception:
    SERPAPI_AVAILABLE = False

def http_get(url: str, timeout=20):
    headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"}
    return requests.get(url, headers=headers, timeout=timeout)

def extract_img_urls_simple(html: str):
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for tag in soup.find_all("img"):
        src = tag.get("src") or tag.get("data-src")
        if src and isinstance(src, str):
            if src.startswith("//"):
                src = "https:" + src
            urls.append(src)
    seen = set(); uniq = []
    for u in urls:
        if u not in seen:
            seen.add(u); uniq.append(u)
    return uniq

def safe_image_download(url: str, max_bytes=8_000_000):
    try:
        r = http_get(url)
        r.raise_for_status()
        if int(r.headers.get("Content-Length", "0")) > max_bytes:
            return None
        return r.content
    except Exception:
        return None

def choose_gallery_image(gallery_url: str):
    try:
        r = http_get(gallery_url)
        if not r.ok: return None, None
        img_urls = extract_img_urls_simple(r.text)
        for u in img_urls[:20]:
            b = safe_image_download(u)
            if b:
                return u, b
    except Exception:
        pass
    return None, None

def zillow_candidate_url(address_full: str, serp_key: str):
    try:
        s = GoogleSearch({"engine":"google","q":f'site:zillow.com \"{address_full}\"', "num":5, "api_key":serp_key, "hl":"en"})
        res = s.get_dict()
        for it in res.get("organic_results", []):
            link = it.get("link")
            if isinstance(link, str) and "zillow.com" in link:
                return link
    except Exception:
        pass
    return None

def choose_zillow_image(zillow_url: str):
    try:
        r = http_get(zillow_url)
        if not r.ok: return None, None
        img_urls = extract_img_urls_simple(r.text)
        for u in img_urls[:40]:
            b = safe_image_download(u)
            if b:
                return u, b
    except Exception:
        pass
    return None, None

def addr_from_row(row, fields):
    parts = [str(row.get(fields["address"],"")).strip(), str(row.get(fields["city"],"")).strip(), str(row.get(fields["state"],"")).strip(), str(row.get(fields["zip"],"")).strip()]
    return ", ".join([p for p in parts if p])

# UI state
if "df" not in st.session_state:
    st.session_state.df = None
if "sheet_name" not in st.session_state:
    st.session_state.sheet_name = None
if "fields" not in st.session_state:
    st.session_state.fields = None
if "serp_key" not in st.session_state:
    st.session_state.serp_key = ""
if "idx" not in st.session_state:
    st.session_state.idx = 0
if "cache" not in st.session_state:
    st.session_state.cache = {}
if "reviewed" not in st.session_state:
    st.session_state.reviewed = set()

with st.sidebar:
    st.header("Setup")
    serp_key = st.text_input("SerpAPI Key", type="password", help="Required for auto-finding Zillow URLs")
    st.session_state.serp_key = serp_key
    limit_rows = st.number_input("Max rows this session", 1, 5000, 100)

uploaded = st.file_uploader("Upload your Excel (.xlsx)", type=["xlsx"])

if uploaded:
    try:
        xls = pd.ExcelFile(uploaded)
        sheet = st.selectbox("Choose sheet", xls.sheet_names, index=0)
        df = pd.read_excel(xls, sheet_name=sheet)
        st.session_state.df = df.copy()
        st.session_state.sheet_name = sheet
        st.success(f"Loaded {len(df)} rows from '{sheet}'")
        st.dataframe(df.head(10), use_container_width=True)
    except Exception as e:
        st.error(f"Failed to read Excel: {e}")

if st.session_state.df is not None:
    df = st.session_state.df
    cols = list(df.columns)
    st.subheader("Map columns")
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        f_addr = st.selectbox("Address", cols)
    with col2:
        f_city = st.selectbox("City", cols)
    with col3:
        f_state = st.selectbox("State", cols)
    with col4:
        f_zip = st.selectbox("ZIP", cols)
    with col5:
        f_gallery = st.selectbox("Share Gallery", cols)
    st.session_state.fields = {"address":f_addr, "city":f_city, "state":f_state, "zip":f_zip, "gallery":f_gallery}

    for c in ["zillow_url","match_type","match_confidence","last_checked_utc","notes"]:
        if c not in df.columns:
            df[c] = ""

    st.divider()
    start = st.button("▶ Start Session")
    if start:
        st.session_state.idx = 0
        st.session_state.cache = {}
        st.session_state.reviewed = set()

    if st.session_state.idx < min(len(df), int(limit_rows)):
        i = st.session_state.idx
        row = df.iloc[i].to_dict()
        addr = addr_from_row(row, st.session_state.fields)
        gal_url = str(row.get(st.session_state.fields["gallery"], "")).strip()

        item = st.session_state.cache.get(i, {})
        if not item:
            zurl = None
            gal_src = None; gal_img = None
            zl_src = None; zl_img = None

            if SERPAPI_AVAILABLE and st.session_state.serp_key and addr:
                zurl = zillow_candidate_url(addr, st.session_state.serp_key)

            if gal_url:
                gal_src, gal_img = choose_gallery_image(gal_url)

            if zurl:
                zl_src, zl_img = choose_zillow_image(zurl)

            item = {"zillow_url": zurl, "gal_src": gal_src, "gal_img": gal_img, "zillow_src": zl_src, "zillow_img": zl_img}
            st.session_state.cache[i] = item

        st.subheader(f"Row {i+1}/{min(len(df), int(limit_rows))}")
        st.caption(addr)

        colA, colB = st.columns(2)
        with colA:
            st.markdown("**Gallery (yours)**")
            if item.get("gal_img"):
                st.image(item["gal_img"], use_column_width=True)
                st.caption(item.get("gal_src") or "")
            else:
                st.warning("No gallery image found")

        with colB:
            st.markdown("**Zillow candidate**")
            if item.get("zillow_img"):
                if item.get("zillow_url"):
                    st.markdown(f"[Open listing]({item['zillow_url']})")
                st.image(item["zillow_img"], use_column_width=True)
                st.caption(item.get("zillow_src") or "")
            else:
                st.warning("No Zillow image found")
                if item.get("zillow_url"):
                    st.markdown(f"[Open listing]({item['zillow_url']})")

        st.divider()
        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("✅ Match", use_container_width=True):
                df.at[i, "zillow_url"] = item.get("zillow_url","")
                df.at[i, "match_type"] = "iUSE-photos"
                df.at[i, "match_confidence"] = "manual"
                df.at[i, "last_checked_utc"] = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
                st.session_state.reviewed.add(i)
                st.session_state.idx += 1
        with b2:
            if st.button("❌ No Match", use_container_width=True):
                df.at[i, "zillow_url"] = ""
                df.at[i, "match_type"] = "other-photos"
                df.at[i, "match_confidence"] = "manual"
                df.at[i, "last_checked_utc"] = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
                st.session_state.reviewed.add(i)
                st.session_state.idx += 1
        with b3:
            if st.button("⏭ Next", use_container_width=True):
                st.session_state.idx += 1

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=st.session_state.sheet_name or "Sheet1", index=False)
        st.download_button("⬇ Download updated Excel", data=buf.getvalue(), file_name="iuse_zillow_results.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.success("Session complete for this batch.")
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            st.session_state.df.to_excel(writer, sheet_name=st.session_state.sheet_name or "Sheet1", index=False)
        st.download_button("⬇ Download updated Excel", data=buf.getvalue(), file_name="iuse_zillow_results.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
