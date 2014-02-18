__author__ = 'elip'

import setuptools

# TODO: test_requires

setuptools.setup(
    zip_safe=True,
    name='cloudify-plugin-openstack-nova-provisioner',
    version='0.1',
    author='elip',
    author_email='itaif@gigaspaces.com',
    packages=['cloudify_plugin_openstack_nova_provisioner'],
    license='LICENSE',
    description='Plugin for provisioning OpenStack Nova',
    install_requires=[
        "cosmo-plugin-openstack-common",
        "python-novaclient" # for novaclient.exceptions.nova_exceptions
    ],
    dependency_links=[
        "https://github.com/ilyash/cosmo-plugin-openstack-common/tarball/" \
        "master#egg=cosmo-plugin-openstack-common-0.1"
    ]
)

