"""Sanity check that the package imports."""


def test_package_version():
    import pm_job_agent

    assert pm_job_agent.__version__ == "0.1.0"
