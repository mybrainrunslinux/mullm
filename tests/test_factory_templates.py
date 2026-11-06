import subprocess
import tomllib

import pytest

from router.factory import FactorySpec
from router.factory_templates import initialize


def test_starter_is_committed_and_cannot_overwrite_existing_work(tmp_path):
    root = initialize('csv-json', tmp_path / 'utility')
    spec = FactorySpec.model_validate(tomllib.loads((root / 'factory.toml').read_text()))
    assert not spec.human_intervention and not spec.questions
    assert all(g.kind == 'command' for g in spec.gates)
    assert not (root / 'convert.py').exists(), 'Implementation must be generated'
    assert subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain']) == b''
    with pytest.raises(ValueError, match='never overwritten'):
        initialize('csv-json', root)
