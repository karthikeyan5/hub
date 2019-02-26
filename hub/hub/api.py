# Copyright (c) 2015, Web Notes Technologies Pvt. Ltd. and Contributors and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import datetime
import frappe
import json

from frappe import _
from frappe.utils import random_string
from six import string_types
from six.moves.urllib.parse import urljoin

from .curation import Curation
from .utils import (
	save_remote_file_locally,
	check_user_and_item_belong_to_same_seller
)

from .log import (
	add_log,
	add_saved_item,
	remove_saved_item,
	get_seller_items_synced_count,
	add_seller_publish_stats,
	add_hub_seller_activity,
)


@frappe.whitelist(allow_guest=True)
def add_hub_seller(company_details):
	"""Register on the hub."""
	try:
		company_details = frappe._dict(json.loads(company_details))

		hub_seller = frappe.get_doc({
			'doctype': 'Hub Seller',
			'company': company_details.company,
			'country': company_details.country,
			'city': company_details.city,
			'currency': company_details.currency,
			'site_name': company_details.site_name,
			'company_description': company_details.company_description
		}).insert(ignore_permissions=True)

		# try and save company logo locally
		company_logo = company_details.company_logo
		if company_logo:
			if company_logo.startswith('/files/'):
				company_logo = urljoin(company_details.site_name, company_logo)

			if company_logo.startswith('http'):
				try:
					logo = save_remote_file_locally(company_logo, 'Hub Seller', hub_seller.name)
					hub_seller.logo = logo.file_url
					hub_seller.save()
				except Exception:
					frappe.log_error(title='Hub Company Logo Exception')


		return {
			'hub_seller_name': hub_seller.name
		}

	except Exception as e:
		print("Hub Server Exception")
		print(frappe.get_traceback())
		frappe.log_error(title="Hub Server Exception")
		frappe.throw(frappe.get_traceback())

@frappe.whitelist(allow_guest=True)
def add_hub_user(user_email, hub_seller, first_name, last_name=None):
	password = random_string(16)

	try:
		user = frappe.get_doc({
			'doctype': 'User',
			'email': user_email,
			'first_name': first_name,
			'last_name': last_name,
			'new_password': password
		})

		user.append_roles('System Manager', 'Hub User', 'Hub Buyer')
		user.flags.delay_emails = True
		user.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		user = frappe.get_doc('User', user_email)
		user.append_roles('System Manager', 'Hub User', 'Hub Buyer')
		user.new_password = password
		user.save(ignore_permissions=True)

	try:
		hub_user = frappe.get_doc({
			'doctype': 'Hub User',
			'hub_seller': hub_seller,
			'user_email': user_email,
			'first_name': first_name,
			'last_name': last_name,
			'user': user.name
		}).insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		hub_user = frappe.get_doc('Hub User', user.name)

	return {
		'user_email': user_email,
		'hub_user_name': hub_user.name,
		'password': password
	}


# @frappe.whitelist()
# def unregister():
# 	frappe.db.set_value('Hub Seller', hub_seller, 'enabled', 0)
# 	return hub_seller


@frappe.whitelist()
def update_profile(hub_seller, updated_profile):
	'''
	Update Seller Profile
	'''

	updated_profile = json.loads(updated_profile)

	profile = frappe.get_doc("Hub Seller", hub_seller)
	if updated_profile.get('company_description') != profile.company_description:
		profile.company_description = updated_profile.get('company_description')

	profile.save()

	return profile.as_dict()

@frappe.whitelist(allow_guest=True)
def get_data_for_homepage(country=None):
	'''
	Get curated item list for the homepage.
	'''
	c = Curation(country=country)
	return c.get_data_for_homepage()


@frappe.whitelist(allow_guest=True)
def get_items(keyword='', hub_seller=None, company=None, filters={}):
	'''
	Get items by matching it with the keywords field
	'''
	if not hub_seller and company:
		hub_seller = frappe.db.get_all(
			"Hub Seller", filters={'company': company})[0].name
	c = Curation()

	if isinstance(filters, string_types):
		filters = json.loads(filters)

	if keyword:
		filters['keywords'] = ['like', '%' + keyword + '%']

	if hub_seller:
		filters["hub_seller"] = hub_seller

	return c.get_items(filters=filters)


@frappe.whitelist()
def pre_items_publish(intended_item_publish_count):
	hub_user = frappe.session.user

	log = add_log(
		log_type = 'Hub Seller Publish',
		hub_user = hub_user,
		data = {
			'status': 'Pending',
			'number_of_items_to_sync': intended_item_publish_count
		}
	)

	# add_hub_seller_activity(
	# 	current_hub_user,
	# 	'Hub Seller Publish',
	# 	{
	# 		'number_of_items_to_sync': intended_item_publish_count
	# 	},
	# 	'Pending'
	# )

	return log


@frappe.whitelist()
def post_items_publish():
	hub_user = frappe.session.user
	items_synced_count = get_seller_items_synced_count(hub_user)

	log = add_log(
		log_type = 'Hub Seller Publish',
		hub_user = hub_user,
		data = {
			'status': 'Completed',
			'items_synced_count': items_synced_count
		}
	)

	# add_hub_seller_activity(
	# 	current_hub_user,
	# 	'Hub Seller Publish',
	# 	{
	# 		'items_synced_count': items_synced_count
	# 	},
	# 	'Completed'
	# )

	add_seller_publish_stats(hub_user)

	return log


@frappe.whitelist(allow_guest=True)
def get_hub_seller_page_info(hub_seller=None, company=None):
	if not hub_seller and company:
		hub_seller = frappe.db.get_all(
			"Hub Seller", filters={'company': company})[0].name
	elif not hub_seller:
		frappe.throw('No Seller or Company Name received.')

	items_by_seller = Curation().get_items(filters={
		'hub_seller': hub_seller,
		'featured_item':1
	})
	is_featured = True
	if len(items_by_seller) == 0:
		is_featured = False
		items_by_seller = Curation().get_items_sorted_by_views(filters={
			'hub_seller': hub_seller
		},limit=8)

	return {
		'profile': get_hub_seller_profile(hub_seller),
		'items': items_by_seller,
		'is_featured_item': is_featured,
		'recent_seller_reviews': get_seller_reviews(hub_seller),
		'seller_product_view_stats': get_seller_product_view_stats(hub_seller)
	}


@frappe.whitelist()
def get_hub_seller_profile(hub_seller=''):
	profile = frappe.get_doc("Hub Seller", hub_seller).as_dict()

	if profile.hub_seller_activity:
		for log in profile.hub_seller_activity:
			log.pretty_date = frappe.utils.pretty_date(log.get('creation'))

	return profile


@frappe.whitelist(allow_guest=True)
def get_item_details(hub_item_name):
	c = Curation()
	items = c.get_items(filters={'name': hub_item_name})
	return items[0] if len(items) == 1 else None


@frappe.whitelist(allow_guest=True)
def get_item_reviews(hub_item_name):
	reviews = frappe.db.get_all('Hub Item Review', fields=['*'],
	filters={
		'parenttype': 'Hub Item',
		'parentfield': 'reviews',
		'parent': hub_item_name
	}, order_by='timestamp desc')

	return reviews or []

@frappe.whitelist(allow_guest=True)
def get_seller_reviews(hub_seller, limit = 4):
	reviews = frappe.db.sql("""
			select c.*
				from `tabHub Item Review` as c,
					`tabHub Item` as p
				where p.name = c.parent
				and p.hub_seller = %(hub_seller)s
				order by c.timestamp desc
				limit {limit}
	""".format(limit=int(limit)),{"hub_seller":hub_seller},as_dict=True)

	return reviews or []

@frappe.whitelist(allow_guest=True)
def get_seller_product_view_stats(hub_seller):
	days = 14
	view_stats = frappe.db.sql("""
	SELECT count(log.name) as view_count, DATE(log.creation) as date
		from `tabHub Item` as item,
			`tabHub Log` as log
		where item.name = log.reference_hub_item
		and log.type = 'Hub Item View'
		and item.hub_seller = %(hub_seller)s
		and log.creation > DATE_SUB(date(now()),INTERVAL %(days)s DAY)
		group by DATE(log.creation)
		order by DATE(log.creation)
	""",{"hub_seller":hub_seller,
		"days":days},as_dict=True)
	
	# result needs to be ordered by date for the below to work as expected
	stats = []
	if len(view_stats) > 0:
		for i in range(days+1):
			date = datetime.date.today() - datetime.timedelta(days=days-i)
			stat = {'view_count':0,'date':date}
			if len(view_stats) > 0 and view_stats[0]['date'] == date:
				stat['view_count'] = view_stats[0]['view_count']
				view_stats.pop(0)
			stats.append(frappe._dict(stat))
		

	return stats

@frappe.whitelist()
def add_item_review(hub_item_name, review):
	'''Adds a review record for Hub Item and limits to 1 per user'''
	new_review = frappe._dict(json.loads(review))
	new_review.user = frappe.session.user
	new_review.timestamp = datetime.datetime.now()

	item_doc = frappe.get_doc('Hub Item', hub_item_name)
	existing_reviews = item_doc.get('reviews')

	# dont allow more than 1 review
	for review in existing_reviews:
		if review.get('user') == new_review.get('user'):
			return dict(error=_('Cannot add more than 1 review for the user {0}').format(new_review.get('user')))

	item_doc.append('reviews', new_review)
	item_doc.save()

	return item_doc.get('reviews')[-1]


@frappe.whitelist(allow_guest=True)
def get_categories(parent='All Categories'):
	# get categories info with parent category and stuff
	categories = frappe.get_all('Hub Category',
		filters={'parent_hub_category': parent},
		fields=['name'],
		order_by='name asc')

	return categories

# Hub Item View

@frappe.whitelist(allow_guest=True)
def add_item_view(hub_item_name):
	hub_user = frappe.session.user
	if hub_user == 'Guest':
		hub_user = None

	log = add_log('Hub Item View', hub_item_name, hub_user)
	return log

# Report Item

@frappe.whitelist()
def add_reported_item(hub_item_name, message=None):
	hub_seller = frappe.session.user

	if message:
		data = {
			'message': message
		}

	log = add_log('Hub Reported Item', hub_item_name, hub_seller, data)
	return log

# Saved Items

@frappe.whitelist()
def add_item_to_user_saved_items(hub_item_name):
	hub_user = frappe.session.user
	log = add_log('Hub Item Save', hub_item_name, hub_user, 1)
	add_saved_item(hub_item_name, hub_user)
	return log


@frappe.whitelist()
def remove_item_from_user_saved_items(hub_item_name):
	hub_user = frappe.session.user
	log = add_log('Hub Item Save', hub_item_name, hub_user, 0)
	remove_saved_item(hub_item_name, hub_user)
	return log


@frappe.whitelist()
def get_saved_items_of_user():
	hub_user = frappe.session.user

	saved_items = frappe.get_all('Hub Saved Item', fields=['hub_item'], filters = {
		'hub_user': hub_user
	})

	saved_item_names = [d.hub_item for d in saved_items]

	return get_items(filters={'name': ['in', saved_item_names]})

# Featured Items

@frappe.whitelist()
def add_item_to_seller_featured_items(hub_item_name):
	hub_user = frappe.session.user
	item_hub_seller_name = frappe.db.get_value('Hub Item', hub_item_name, fieldname=['hub_seller'])

	check_user_and_item_belong_to_same_seller(hub_user,hub_item_name)
	
	# validation: max 8 featured items per seller
	if frappe.db.count('Hub Item' ,{'hub_seller':item_hub_seller_name,'featured_item':1}) >= 8:
		frappe.throw(_("You already have 8 featured items. You can feature only 8 items."))
	
	log = add_log('Hub Feature Item', hub_item_name, hub_user, 1)
	frappe.db.set_value("Hub Item", hub_item_name, "featured_item", 1)
	return log


@frappe.whitelist()
def remove_item_from_seller_featured_items(hub_item_name):
	hub_user = frappe.session.user

	check_user_and_item_belong_to_same_seller(hub_user,hub_item_name)

	log = add_log('Hub Feature Item', hub_item_name, hub_user, 0)
	frappe.db.set_value("Hub Item", hub_item_name, "featured_item", 0)
	return log


@frappe.whitelist()
def get_featured_items_of_seller():
	hub_user = frappe.session.user
	user_hub_seller_name = frappe.db.get_value('Hub User', hub_user, fieldname=['hub_seller'])

	return get_items(filters={
		'hub_seller': user_hub_seller_name,
		'featured_item':1
	})

@frappe.whitelist()
def get_sellers_with_interactions(for_seller):
	'''Return all sellers `for_seller` has sent a message to or received a message from'''

	res = frappe.db.sql('''
		SELECT sender, receiver
		FROM `tabHub Seller Message`
		WHERE sender = %s OR receiver = %s
	''', [for_seller, for_seller])

	sellers = []
	for row in res:
		sellers += row

	sellers = [seller for seller in sellers if seller != for_seller]

	sellers_with_details = frappe.db.get_all('Hub Seller',
											 fields=['name as email', 'company'],
											 filters={'name': ['in', sellers]})

	return sellers_with_details


@frappe.whitelist()
def get_messages(against_item, against_seller=None, order_by='creation asc', limit=None):
	'''Return all messages exchanged between seller of item and seller of hub_user'''

	hub_user = frappe.session.user
	hub_seller = get_hub_seller_of_user(hub_user)

	if not against_seller:
		against_seller = frappe.db.get_value('Hub Item', against_item, 'hub_seller')

	hub_user_details = frappe.db.get_all('Hub User', fields=['name', 'first_name'],
		filters={ 'hub_seller': ['in', [hub_seller, against_seller]] })

	hub_users = [hub_user.name for hub_user in hub_user_details]

	messages = frappe.get_all('Hub Chat Message',
		fields=['name', 'sender', 'message', 'creation'],
		filters={
			'sender': ['in', hub_users],
			'reference_hub_item': against_item,
		}, limit=limit, order_by=order_by)

	for message in messages:
		hub_user = list(filter(lambda x: x.name == message.sender, hub_user_details))[0]
		message.sender_name = hub_user.first_name

	return messages

@frappe.whitelist()
def get_buying_items_for_messages():
	hub_user = frappe.session.user
	hub_seller = get_hub_seller_of_user(hub_user)

	items = frappe.db.get_all('Hub Chat Message',
		fields='reference_hub_item',
		filters={
			'reference_hub_seller': ('!=', hub_seller)
		},
		group_by='reference_hub_item'
	)

	item_names = [item.reference_hub_item for item in items]

	items = get_items(filters={ 'name': ['in', item_names] })

	for item in items:
		item['recent_message'] = get_recent_message(item)

	return items

@frappe.whitelist()
def get_selling_items_for_messages():
	hub_user = frappe.session.user
	hub_seller = get_hub_seller_of_user(hub_user)
	hub_users = get_hub_users_of_seller(hub_seller)

	items = frappe.db.get_all('Hub Chat Message',
		fields='reference_hub_item',
		filters={
			'reference_hub_seller': hub_seller
		},
		group_by='reference_hub_item'
	)

	item_names = [item.reference_hub_item for item in items]

	items = get_items(filters={
		'name': ['in', item_names]
	})

	for item in items:
		item.received_messages = frappe.get_all('Hub Chat Message',
			fields=['sender', 'message', 'creation', 'hub_item_belongs_to_sender'],
			filters={
				'sender': ['not in', hub_users],
				'reference_hub_item': item.name
			}, distinct=True, order_by='creation DESC')

		for message in item.received_messages:
			message.buyer = get_hub_seller_of_user(message.sender)
			message.buyer_name = frappe.db.get_value('Hub Seller', message.buyer, 'company')

	return items


@frappe.whitelist()
def send_message(message, hub_item):
	hub_user = frappe.session.user

	msg = frappe.get_doc({
		'doctype': 'Hub Chat Message',
		'sender': hub_user,
		'message': message,
		'reference_hub_item': hub_item
	}).insert(ignore_permissions=True)

	return msg

@frappe.whitelist(allow_guest=True)
def ping():
	return frappe.session.user

def validate_session_user(user):
	if frappe.session.user == 'Administrator':
		return True
	if frappe.session.user != user:
		frappe.throw(_('Not Permitted'), frappe.PermissionError)

def get_recent_message(item):
	message = get_messages(item.name, limit=1, order_by='creation desc')
	message_object = message[0] if message else {}
	return message_object

def get_hub_seller_of_user(hub_user):
	return frappe.db.get_value('Hub User', hub_user, 'hub_seller')

def get_hub_users_of_seller(hub_seller):
	return [user.name for user in frappe.db.get_all('Hub User', filters={ 'hub_seller': hub_seller })]