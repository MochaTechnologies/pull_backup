# Copyright (c) 2015, Web Notes Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

from __future__ import unicode_literals, absolute_import, print_function
import click
import frappe
import requests
import base64
import os
import sys
import glob
import json
from frappe.commands import pass_context, get_site
from frappe.commands.site import _restore
from frappe.utils import get_site_path
from frappe.migrate import migrate
from six.moves.urllib.parse import urlencode


def call_command(cmd, context):
	return click.Context(cmd, obj=context).forward(cmd)


@click.command('pull-backup')
@click.option('--site', help='site name')
@click.option('--remote', help='URL of remote Frappe instance')
@click.option('--api-key', help='URL of remote Frappe instance')
@click.option('--api-secret', help='URL of remote Frappe instance')
@click.option('--mariadb-root-username', default='root', help='Root username for MariaDB')
@click.option('--mariadb-root-password', help='Root password for MariaDB')
@pass_context
def pull_backup(context, site, remote, api_key, api_secret, mariadb_root_username=None, mariadb_root_password=None):
	site = get_site(context)
	frappe.init(site=site)

	site_path = get_site_path()
	remote_backup_dir = os.path.join(site_path, 'private/remote_backups')

	config_file_path = os.path.join(site_path, "pull_backup.json")
	config = frappe._dict()
	if os.path.exists(config_file_path):
		with open(config_file_path, 'r') as f:
			config = frappe._dict(json.loads(f.read()))

	remote = remote or config.remote_url
	if not remote:
		print('Remote URL not provided')
		sys.exit(1)

	if not remote.endswith('/'):
		remote = remote + '/'

	api_key = api_key or config.api_key
	api_secret = api_secret or config.api_secret
	if not api_key or not api_secret:
		print('API Key not provided')
		sys.exit(1)

	base_url = remote
	backups_query_url = base_url + "api/method/frappe.utils.backups.fetch_latest_backups"

	def get_download_url(fn):
		return base_url + "api/method/pull_backup.download_backup?{0}".format(urlencode({'filename': fn}))

	api_concat = "{}:{}".format(api_key, api_secret)
	api_encoded = base64.b64encode(api_concat.encode('utf-8'))
	api_encoded = api_encoded.decode()
	headers = {
		'Authorization': "Basic {}".format(api_encoded)
	}

	query_response = requests.get(backups_query_url, headers=headers)
	r = query_response.json().get('message')

	files_remote = frappe._dict({
		'database': r.get('database'),
		'public': r.get('public'),
		'private': r.get('private')
	})
	files_local = frappe._dict({})

	if not files_remote.database:
		print('No backup available in remote site')
		sys.exit(1)

	if not os.path.exists(remote_backup_dir):
		os.makedirs(remote_backup_dir)

	to_remove = glob.glob(os.path.join(remote_backup_dir, '*'))
	for fn in to_remove:
		os.remove(fn)

	for filetype in files_remote:
		filename = os.path.basename(files_remote.get(filetype)) if files_remote.get(filetype) else None
		files_remote[filetype] = filename
		files_local[filetype] = os.path.join(remote_backup_dir, filename) if filename else None

	for filetype, filename in files_remote.items():
		print("{0}: {1}".format(filetype, filename))

	for filetype, filename in files_remote.items():
		if filename:
			download_url = get_download_url(filename)
			print("Downloading {0}".format(download_url))

			download_response = requests.get(download_url, headers=headers)

			if is_downloadable(download_response):
				open(files_local.get(filetype), 'wb').write(download_response.content)
			else:
				print('Invalid file received')
				sys.exit(1)

	mariadb_root_username = mariadb_root_username or config.mariadb_root_username
	mariadb_root_password = mariadb_root_password or config.mariadb_root_password
	_restore(context, files_local.database, with_public_files=files_local.public, with_private_files=files_local.private,
		mariadb_root_username=mariadb_root_username, mariadb_root_password=mariadb_root_password)
	migrate()


def is_downloadable(response):
	header = response.headers
	content_type = header.get('content-type')
	if 'text' in content_type.lower():
		return False
	if 'html' in content_type.lower():
		return False
	return True


commands = [
	pull_backup
]
