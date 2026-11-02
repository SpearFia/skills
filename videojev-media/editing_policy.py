# SPDX-License-Identifier: MIT OR Apache-2.0
"""Creator's current experiment boundary, separate from project/channel settings."""
import math
import re
from pathlib import Path

MOTIONS = ('pop',)
MAX_STUDY_SECONDS = 120
DEPLOYMENT_ENABLED = False
PROTECTED_PROJECTS = ('cwi003','cwi004completegtastory','gtahistory')


def require_short_study(duration_seconds,*paths):
    if type(duration_seconds) not in (int,float) or not math.isfinite(duration_seconds) or not 0<duration_seconds<=MAX_STUDY_SECONDS:
        raise ValueError('Editing experiments are limited to complete videos of two minutes or less')
    for path in paths:
        for part in re.split(r'[/\\]',str(path)):
            name=re.sub(r'[^a-z0-9]','',part.casefold())
            if any(project in name for project in PROTECTED_PROJECTS):
                raise ValueError('Current John Wick and GTA History projects are excluded from editing experiments')


def require_short_native(sequence,project):
    clips=[c for key in ['video_tracks','audio_tracks'] for t in sequence[key] for c in t['items']]
    duration=max((c['start']+c['duration'] for c in clips),default=0)/254016000000
    require_short_study(duration,Path(project))


def require_deployment():
    if not DEPLOYMENT_ENABLED:
        raise RuntimeError('Experimental editing deployment is disabled by the creator; use recommendation-only short studies')
