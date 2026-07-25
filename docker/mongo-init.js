// Local development only. These databases contain no production data.
db = db.getSiblingDB("hymn_local");
db.createCollection("_local_setup");

db = db.getSiblingDB("hymn_test");
db.createCollection("_local_setup");
