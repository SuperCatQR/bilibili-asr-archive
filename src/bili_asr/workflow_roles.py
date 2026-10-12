"""Worker role names and job capabilities without application adapters."""
from bili_asr.workflow_models import JobKind

WORKER_ROLES = {
    "asr": (JobKind.ASR,),
    "acquisition": (JobKind.SUBTITLE, JobKind.AUDIO),
    "editorial": (JobKind.PROOFREAD, JobKind.RENDER_DOCUMENT),
    "cpu": (JobKind.SUBTITLE, JobKind.AUDIO, JobKind.PUBLISH),
}
