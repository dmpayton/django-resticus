# Django Resticus

![Resticus Logo](resticus_logo.svg)

[![Build Status](https://secure.travis-ci.org/dmpayton/django-resticus.png?branch=master)](http://travis-ci.org/dmpayton/django-resticus)
[![Code Climate](https://codeclimate.com/github/dmpayton/django-resticus/badges/gpa.svg)](https://codeclimate.com/github/dmpayton/django-resticus)
[![Coverage Status](https://coveralls.io/repos/dmpayton/django-resticus/badge.png)](https://coveralls.io/r/dmpayton/django-resticus)

Resticus is a lightweight set of tools for implementing JSON-based
RESTful APIs in Django. It helps with writing APIs that loosely follow
the RESTful paradigm, without forcing you to do so, and without imposing a
full-blown REST framework.

Resticus provides only JSON support. If you need to support XML or
other formats, you probably want to take a look at some of the other frameworks
out there (we recommend Django REST framework).

Here is a simple view implementing an API endpoint greeting the caller:

    from restless.views import Endpoint

    class HelloWorld(Endpoint):
        def get(self, request):
            name = request.params.get('name', 'World')
            return {'message': 'Hello, %s!' % name}

One of the main ideas behind Resticus is that it's lightweight and reuses
as much of functionality in Django as possible. For example, input parsing and
validation is done using standard Django forms. This means you don't have to
learn a whole new API to use Resticus.

## Installation

Django Resticus is available from cheeseshop, so you can install it via pip:

    pip install django-resticus

For the latest and the greatest, you can also get it directly from git master:

    pip install git+ssh://github.com/dmpayton/django-resticus/tree/master

The supported Python versions are 2.6, 2.7, 3.3 and 3.4, and the supported
Django versions are 1.5+.

## Documentation

Documentation is graciously hosted by ReadTheDocs: http://django-resticus.rtfd.org/

## License

Copyright (C) 2012-2015 by Django Resticus contributors. See the
[AUTHORS](AUTHORS.md) file for the list of contributors.

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
