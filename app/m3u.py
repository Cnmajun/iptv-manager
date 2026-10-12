"""M3U parse / build + channel name normalization for dedup merge."""
import re
from dataclasses import dataclass

EXTINF_RE = re.compile(r'#EXTINF:-?\d+\s*(.*)', re.IGNORECASE)
ATTR_RE = re.compile(r'([\w\-]+)="([^"]*)"')
# Common quality suffixes stripped during normalization so "CCTV1 HD"
# merges with "CCTV1". \u00b7 is the middle dot sometimes used as separator.
QUALITY_SUFFIX_RE = re.compile(
    r'[\s\-_\u00b7.]*(\(?(4k|8k|uhd|fhd|hd|sd)\)?)[\s\-_\u00b7.]*$',
    re.IGNORECASE,
)
# CJK brackets \u3010 \u3011 (and ascii []) often wrap remarks: strip them.
BRACKET_RE = re.compile(r'[\u3010\[][^\u3011\]]*[\u3011\]]')
CJK_QUALITY_WORDS = ('\u9ad8\u6e05', '\u8d85\u6e05', '\u6807\u6e05',
                     '\u6d41\u7545', '\u84dd\u5149')


@dataclass
class ParsedChannel:
    name: str
    url: str
    logo: str = ""
    tvg_id: str = ""
    tvg_name: str = ""
    group: str = ""


def normalize_name(name: str) -> str:
    """Normalize a channel name: drop spaces/case/quality suffixes/bracket
    remarks, so variants count as the same channel for merging."""
    n = (name or '').strip().lower()
    n = re.sub(r'\s+', '', n)
    for _ in range(3):
        new = QUALITY_SUFFIX_RE.sub('', n)
        if new == n:
            break
        n = new
    for w in CJK_QUALITY_WORDS:
        if n.endswith(w):
            n = n[: -len(w)]
    n = BRACKET_RE.sub('', n)
    n = re.sub(r'[-_.\u00b7]', '', n)
    return n


def parse_m3u(text: str) -> list:
    """Parse M3U text into ParsedChannel list. Tolerates missing header,
    blank lines and comment lines."""
    channels = []
    pending = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith('#EXTINF'):
            m = EXTINF_RE.match(line)
            attrs = dict(ATTR_RE.findall(m.group(1))) if m else {}
            name = line.rsplit(',', 1)[-1].strip() if ',' in line else ''
            if not name:
                name = attrs.get('tvg-name', '').strip()
            pending = ParsedChannel(
                name=name,
                url='',
                logo=attrs.get('tvg-logo', ''),
                tvg_id=attrs.get('tvg-id', ''),
                tvg_name=attrs.get('tvg-name', ''),
                group=attrs.get('group-title', ''),
            )
        elif line.startswith('#'):
            continue
        else:
            if pending is not None and pending.name:
                pending.url = line
                channels.append(pending)
            pending = None
    return channels


def build_m3u(channels: list, title: str = 'IPTV') -> str:
    """Build M3U text from channel objects with name/url/logo/tvg_id/category."""
    out = ['#EXTM3U']
    for c in channels:
        logo = (c.logo or '').replace('"', '')
        tvg_id = (c.tvg_id or '').replace('"', '')
        group = (c.category or '').replace('"', '')
        name = (c.name or '').replace(',', ' ')
        out.append(
            '#EXTINF:-1 tvg-id="%s" tvg-logo="%s" group-title="%s",%s'
            % (tvg_id, logo, group, name)
        )
        out.append(c.url)
    return '\n'.join(out) + '\n'
