#!/usr/bin/env python3
"""Test image transformation logic"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.utils import ImageTransformer, ImageQuality

# Test URLs
test_urls = [
    "https://rvb-img.reverb.com/image/upload/s--u94pKSb---/f_auto,t_large/v1756373398/a5s7yex1zki69hqmi7tc.jpg",
    "https://rvb-img.reverb.com/image/upload/s--k5jtQgjw--/a_0/f_auto,t_large/v1748246175/image.jpg",
    "https://rvb-img.reverb.com/image/upload/a_0/f_auto,t_large/v1748246175/image.jpg"
]

print("Testing ImageTransformer.transform_reverb_url with MAX_RES:\n")

for url in test_urls:
    max_res = ImageTransformer.transform_reverb_url(url, ImageQuality.MAX_RES)
    print(f"Original: {url}")
    print(f"MAX_RES:  {max_res}")
    print(f"Expected: https://rvb-img.reverb.com/image/upload/v{url.split('/v')[1]}")
    print("-" * 80)