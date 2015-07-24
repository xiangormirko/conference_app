App Engine application for the Udacity Project 4 completed by Xiang Zhao Mirko 07/23/2015

## General Description
This is an app using google appengine cloud API endpoints with front end design to create and register for conferences and the appropriate sessions. 

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions

1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting your local server's address (by default [localhost:8080][5].)
1. (Optional) Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.

## Data Modeling

	### Session class
	Session inherits from ndb.model and is used to implement sub chapters of Conferences. Conference is also the parent class for sessions. Contained within the class are the properties: name, highlights, speaker, duration, typeOfSession, date, and startTime. The corresponding SesssionForm to be used as inbount and outbound message form contains all the above properties as well as websafeConferenceKey and websafeKey to easily reconstruct the associated conference and the session itself.

	### Session properties
	| Property        | Type                         |
	|-----------------|------------------------------|
	| name            | stringProperty, required     |
	| highlights      | stringProperty               |
	| speaker         | stringProperty               |
	| duration        | integerProperty              |
	| typeOfSession   | stringProperty, repeated     |
	| date            | dateProperty                 |
	| startTime       | timeProperty                 |

	### Speaker class
	Speaker is a separate Kind used to register speakers. It includes properties: name (required), main email (required and used as id), intro (for a frief intro of the speaker), and sessionKeysToAttend (To gather all sessions where the speaker will be speaking). The related SpeakerForm includes all the above mentioned properties as well as a websafeKey


	### Speaker properties
	| Property            | Type                     |
	|---------------------|--------------------------|
	| name                | stringProperty, required |
	| intro               | stringProperty           |  * a short intro for the speaker
	| mainEmail           | stringProperty           |  * main email also used as id
	| sessionKeysToAttend | stringProperty           | 	


	### Wishlist class
	Wishlist is a class that is associated with each user. User are able to insert sessions into the list and later retrieve them. 


	### Wishlist properties
	| Property        | Type                         |
	|-----------------|------------------------------|
	| ownerId         | stringProperty, required     |
	| SessionInList   | stringProperty, repeated     |  * contains a list of keys of sessions 
	| public          | booleanProperty              |  * to determine if the wishlist shall be publicly visible





## Additional Queries

	getSessionsWithSeats: A query to fetch all sessions attached to a conference that still has available seats
	Users may use this query to conveniently exlude all sessions that are sold out

	getSessionsAfterTime: A query to fetch all sessions happening after a given time. The endpoints method takes in a 
	time in the "hhmm" (eg 1430 instead of 14:30)format without colen in the middle which may cause path problems. 

## Inequality filter problem

	The given problem of exluding workshops and sessions after 7pm presents a double inequality filter problem. As ndb is capped to one property inequality, this may present an issue.

	Proposed solution
	Do one inequality filter at a time. First get all non-workshop sessions. Then filter the result to exclude all sessions after 7pm


## Memcache of featured speaker

	When a new session is added, a new task in queued to check if the speaker has one or more sessions present in the database. If yet, the name of the speaker and the related sessions are added in the memecache as a message. 



[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool
