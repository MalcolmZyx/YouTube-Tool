"""Labeling comments for the constructive-criticism classifier.

* comments.py: reads the crawled comments in MongoDB and builds the queue.
* labels.py: records decisions in Postgres (`comment_label`) and undoes them.
* stats.py: progress counts and the share of constructive comments with its interval.

The page and the reasoning are described in docs/concepts/labeling.md.
"""
