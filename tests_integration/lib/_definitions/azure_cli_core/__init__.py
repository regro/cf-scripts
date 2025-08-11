from pathlib import Path

from fastapi import APIRouter

from ..base_classes import AbstractIntegrationTestHelper, TestCase


class GrayskullV1VersionUpdate(TestCase):
    def get_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/pypi.org/pypi/azure-cli-core/json")
        def handle_pypi_json_api():
            return {
                # rest omitted
                "info": {"name": "azure-cli-core", "version": "2.76.0"}
            }

        @router.get("/pypi.org/pypi/azure-cli-core/2.76.0/json")
        def handle_pypi_version_json_api():
            # Required to execute 'get_dep_updates_and_hints' in DependencyUpdateMigrator.
            return {
                "info": {
                    "author": "Microsoft Corporation",
                    "author_email": "azpycli@microsoft.com",
                    "bugtrack_url": None,
                    "classifiers": [
                        "Development Status :: 5 - Production/Stable",
                        "Intended Audience :: Developers",
                        "Intended Audience :: System Administrators",
                        "License :: OSI Approved :: MIT License",
                        "Programming Language :: Python",
                        "Programming Language :: Python :: 3",
                        "Programming Language :: Python :: 3.10",
                        "Programming Language :: Python :: 3.11",
                        "Programming Language :: Python :: 3.12",
                        "Programming Language :: Python :: 3.9",
                    ],
                    "description": "Microsoft Azure CLI Core Module\n==================================\n\nRelease History\n===============\n\nSee `Release History on GitHub <https://github.com/Azure/azure-cli/blob/dev/src/azure-cli-core/HISTORY.rst>`__.\n",
                    "description_content_type": None,
                    "docs_url": None,
                    "download_url": None,
                    "downloads": {"last_day": -1, "last_month": -1, "last_week": -1},
                    "dynamic": None,
                    "home_page": "https://github.com/Azure/azure-cli",
                    "keywords": None,
                    "license": "MIT",
                    "license_expression": None,
                    "license_files": None,
                    "maintainer": None,
                    "maintainer_email": None,
                    "name": "azure-cli-core",
                    "package_url": "https://pypi.org/project/azure-cli-core/",
                    "platform": None,
                    "project_url": "https://pypi.org/project/azure-cli-core/",
                    "project_urls": {"Homepage": "https://github.com/Azure/azure-cli"},
                    "provides_extra": None,
                    "release_url": "https://pypi.org/project/azure-cli-core/2.76.0/",
                    "requires_dist": [
                        "argcomplete~=3.5.2",
                        "azure-cli-telemetry==1.1.0.*",
                        "azure-mgmt-core<2,>=1.2.0",
                        "cryptography",
                        'distro; sys_platform == "linux"',
                        "humanfriendly~=10.0",
                        "jmespath",
                        "knack~=0.11.0",
                        "microsoft-security-utilities-secret-masker~=1.0.0b4",
                        "msal-extensions==1.2.0",
                        'msal[broker]==1.33.0b1; sys_platform == "win32"',
                        'msal==1.33.0b1; sys_platform != "win32"',
                        "packaging>=20.9",
                        "pkginfo>=1.5.0.1",
                        'psutil>=5.9; sys_platform != "cygwin"',
                        "PyJWT>=2.1.0",
                        "pyopenssl>=17.1.0",
                        "py-deviceid",
                        "requests[socks]",
                    ],
                    "requires_python": ">=3.9.0",
                    "summary": "Microsoft Azure Command-Line Tools Core Module",
                    "version": "2.76.0",
                    "yanked": False,
                    "yanked_reason": None,
                },
                "last_serial": 30520192,
                "urls": [
                    {
                        "comment_text": None,
                        "digests": {
                            "blake2b_256": "300ef0890dfd0ee487e784f19e6c47947848501e3b2c977715aa80032e4e0d2b",
                            "md5": "fb8194ea0ee6f8fef74bf392ab29b6e7",
                            "sha256": "281afe732ac6f85a39b6535466ac2e919c9c83d304ee67ef471f70ce16ecbb67",
                        },
                        "downloads": -1,
                        "filename": "azure_cli_core-2.76.0-py3-none-any.whl",
                        "has_sig": False,
                        "md5_digest": "fb8194ea0ee6f8fef74bf392ab29b6e7",
                        "packagetype": "bdist_wheel",
                        "python_version": "py3",
                        "requires_python": ">=3.9.0",
                        "size": 260181,
                        "upload_time": "2025-08-05T03:04:16",
                        "upload_time_iso_8601": "2025-08-05T03:04:16.436810Z",
                        "url": "https://files.pythonhosted.org/packages/30/0e/f0890dfd0ee487e784f19e6c47947848501e3b2c977715aa80032e4e0d2b/azure_cli_core-2.76.0-py3-none-any.whl",
                        "yanked": False,
                        "yanked_reason": None,
                    },
                    {
                        "comment_text": None,
                        "digests": {
                            "blake2b_256": "5ccf703679ee9c73e52e523cfa6f1feaa516b4e13297dd765e8c9e28496d0382",
                            "md5": "1fc89d88c47f002b71848b5c95f7bc1f",
                            "sha256": "97dbcc4557589cb68356d9f5c3793ecf5d86118622dc78835057e029c7698a95",
                        },
                        "downloads": -1,
                        "filename": "azure_cli_core-2.76.0.tar.gz",
                        "has_sig": False,
                        "md5_digest": "1fc89d88c47f002b71848b5c95f7bc1f",
                        "packagetype": "sdist",
                        "python_version": "source",
                        "requires_python": ">=3.9.0",
                        "size": 229508,
                        "upload_time": "2025-08-05T03:04:11",
                        "upload_time_iso_8601": "2025-08-05T03:04:11.911532Z",
                        "url": "https://files.pythonhosted.org/packages/5c/cf/703679ee9c73e52e523cfa6f1feaa516b4e13297dd765e8c9e28496d0382/azure_cli_core-2.76.0.tar.gz",
                        "yanked": False,
                        "yanked_reason": None,
                    },
                ],
                "vulnerabilities": [],
            }

        return router

    def prepare(self, helper: AbstractIntegrationTestHelper):
        feedstock_dir = Path(__file__).parent / "resources" / "feedstock"
        helper.overwrite_feedstock_contents("azure-cli-core", feedstock_dir)

    def validate(self, helper: AbstractIntegrationTestHelper):
        helper.assert_version_pr_present_v1(
            "azure-cli-core",
            new_version="2.76.0",
            new_hash="97dbcc4557589cb68356d9f5c3793ecf5d86118622dc78835057e029c7698a95",
            old_version="2.75.0",
            old_hash="0187f93949c806f8e39617cdb3b4fd4e3cac5ebe45f02dc0763850bcf7de8df2",
        )
        helper.assert_new_runtime_requirements_equal(
            "azure-cli-core",
            new_version="2.76.0",
            runtime_requirements=[
                "python >=${{ python_min }}",
                "argcomplete >=3.5.2,<3.6.dev0",
                "azure-cli-telemetry ==1.1.0.*",
                "azure-mgmt-core >=1.2.0,<2",
                "cryptography",
                "distro",
                "humanfriendly >=10.0,<11.dev0",
                "jmespath",
                "knack >=0.11.0,<0.12.dev0",
                "microsoft-security-utilities-secret-masker >=1.0.0b4,<1.1.dev0",
                "msal ==1.33.0b1",
                "msal_extensions ==1.2.0",
                "packaging >=20.9",
                "pkginfo >=1.5.0.1",
                "psutil >=5.9",
                "py-deviceid",
                "pyjwt >=2.1.0",
                "pyopenssl >=17.1.0",
                "requests",
            ],
        )


ALL_TEST_CASES: list[TestCase] = [GrayskullV1VersionUpdate()]
