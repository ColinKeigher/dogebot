'''
Dogecoin plugin for Skybot

This is public domain so please feel free to use as you please.

Commands:
---------
.tip set <address> - Allows someone to set an address to their nickname
.tip send <user> - Sends a random amount of DOGE to a specific user
.tip info [user] - Shows details about a user (how much received, their address)
.tip - Shows general statistics
'''

from util import hook

import random
import time

import dogecoinrpc
from dogecoinrpc.exceptions import InsufficientFunds

public_address = ''

# Creates the random amount based on a list of odds.
def random_amount():
	# <1% for 10 DOGE, 2% for 8-9 DOGE, 5% for 5-7 DOGE, 93% chance for 1-4 DOGE
	groups = [ 1 for w in xrange(0, 25000) ] + [ 2 for x in xrange(0, 1000) ] + [ 3 for y in xrange(0, 500) ] + [ 4 for z in xrange(0, 100) ]
	group_amounts = { 1: xrange(1, 50), 2: xrange(50, 80), 3: xrange(80, 100), 4: [ 100 ] }
	group_choice = random.choice(groups)
	candidates = group_amounts[group_choice]
	return random.choice(candidates)

'''
A lot of this was written when trying to figure out Skybot's API. This should and can be merged into the items below but 
it works for now.
'''

def db_init(db):
	q = 'create table if not exists dogetip_users (nick, amt_received, address, senttip, lasttip)'
	db.execute(q)
	q = 'create table if not exists dogetip_transactions (sender, receiver, amount, timestamp)'
	db.execute(q)
	db.commit()

def db_new_user(db, nick, address):
	q = 'insert into dogetip_users (nick, amt_received, address, senttip, lasttip) values (?, ?, ?, ?, ?)'
	db.execute(q, (nick, 0, address, 0, 0))
	db.commit()

def db_update_user(db, nick, address):
	q = 'update dogetip_users set address = ? where nick = ?'
	db.execute(q, (address, nick))
	db.commit()

def db_info_user(db, nick):
	q = 'select * from dogetip_users where nick = ? limit 1'
	return db.execute(q, (nick, )).fetchall()

def db_transaction(db, sender, receiver, amount):
	q_record = 'insert into dogetip_transactions (sender, receiver, amount, timestamp) values (?, ?, ?, ?)'

def db_user_exist(db, username):
	q = 'select count(*) from dogetip_users where nick = ?'
	dball = db.execute(q, (username, ))


'''
Way too many if-elses here. I wrote this in like 2 hours after grabbing the Skybot code and figuring out
the RPC for Dogecoind. Certainly issue a pull request to make this less terrible.
'''

@hook.command('tip')
def dogetip(inp, nick='', chan='', db=None):
	valid = [ 'send', 'set', 'info' ]
	if inp == '':
		a = accounting(db)
		output = 'Amount available: %s DOGE Donate: %s (Available options: %s)' % (a.available_funds(), public_address, ', '.join(valid))
	else:
		option = inp.split()[0]
		if option in valid:
			db_init(db) 
			try:
				dest = inp.split()[1]
			except:
				dest = None
			if option == 'send':
				if dest == None:
					output = 'Usage: .tip send [user]'
				else:
					a = accounting(db, send=nick, recv=dest)
					if a.valid_destination() and a.available_possible() and nick != dest:
						amount = random_amount()
						a.execute(amount)
						output = '%d DOGE has been awarded to %s.' % (amount, dest)
					else:
						if nick == dest:
							output = 'You cannot tip yourself.'
						else:
							output = 'Cannot send to %s due to no available address or funds are locked.' % dest
			if option == 'set':
				if dest != None:
					a = accounting(db, recv=nick)
					if a.valid_user():
						db_update_user(db, nick, dest)
						output = 'Changed address to %s.' % (dest)
					else:
						db_new_user(db, nick, dest)
						output = '%s has been set as your Dogecoin address.' % dest
				else:
					output = 'Usage: .tip set [address]'
			if option == 'info':
				if dest == None:
					dest = nick
				a = accounting(db, recv=dest)
				if a.valid_user():
					data = a.user_detail()
					output = 'User: %s Address: %s Received: %d' % (data[0], data[2], data[1])
				else:
					output = 'No details on %s.' % dest
	return output 

class accounting():
	def __init__(s, db, send=None, recv=None):
		s.address_bot = public_address
		s.db = db
		s.doge = dogecoin_api(s.address_bot)
		s.donation_recipient = recv
		s.donation_sender = send
		s.float = 11000 # Used to allow for the wallet to "float"
		s.max_donation_per_user_24h = 10 # maximum tips to a person per day
		s.max_donation_per_24h = 100 # Max donations per day
		s.time_between_donation = 1 # minutes between each tip allowed
		s.time_now = time.time()
		s.time_last_24h = s.time_now - (24*60*60) # epoch time from yesterday

	# Returns t/f based on s.time_between_donation
	def _transaction_breather(s):
		q = 'select timestamp from dogetip_transactions where timestamp > ? and timestamp < ?'
		timethen = s.time_now - (s.time_between_donation * 60)
		data = s.db.execute(q, (timethen, s.time_now)).fetchall()
		return len(data) == 0

	# Determines if too many have been sent to a user 
	def _transaction_recent_recv(s):
		q = 'select timestamp from dogetip_transactions where timestamp > ? and timestamp < ? and receiver = ?'
		data = s.db.execute(q, (s.time_last_24h, s.time_now, s.donation_recipient)).fetchall()
		return len(data) <= s.max_donation_per_user_24h

	# Checks to make sure a transaction can go through
	def _transaction_possible(s):
		current_amt = s.doge.available()
		possible = current_amt > s.float
		return possible

	# Registers the tip used
	def _transaction_register(s, amount):
		q = 'insert into dogetip_transactions (sender, receiver, amount, timestamp) values (?, ?, ?, ?)'
		s.db.execute(q, (s.donation_sender, s.donation_recipient, amount, s.time_now))
		q = 'update dogetip_users set amt_received = amt_received + ?, lasttip = ? where nick = ?'
		s.db.execute(q, (amount, s.time_now, s.donation_recipient))
		q = 'update dogetip_users set senttip = ? where nick = ?'
		s.db.execute(q, (s.time_now, s.donation_sender))
		s.db.commit()

	def _user_details(s):
		data = db_info_user(s.db, s.donation_recipient)
		return data[0]

	def _valid_user(s):
		return len(db_info_user(s.db, s.donation_recipient)) > 0

	def available_funds(s):
		return s.doge.available() - s.float

	def available_possible(s):
		return s._transaction_possible()

	def execute(s, amount):
		address = s.user_detail()[2]
		s._transaction_register(amount)
		s.doge = dogecoin_api(address)
		s.doge.send(amount)

	def user_detail(s):
		return s._user_details()

	def valid_user(s):
		return s._valid_user()

	def valid_destination(s):
		print [ s._valid_user(), s._transaction_breather(), s._transaction_recent_recv() ]
		return False not in [ s._valid_user(), s._transaction_breather(), s._transaction_recent_recv() ]

# Very, very simple interface to dogecoind
class dogecoin_api():
	def __init__(s, address=None):
		s.conn = dogecoinrpc.connect_to_local()
		s.destination = address

	def available(s):
		return int(s.conn.getbalance())

	def send(s, amount):
		s.conn.sendtoaddress(s.destination, amount)

	