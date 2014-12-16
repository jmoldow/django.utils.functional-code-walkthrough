# coding: utf-8

from __future__ import unicode_literals
import functools
import itertools

from django.utils import functional as django_functional

class DjangoFunctionalUtils(object):
    def _proxy_method(self, *args, **kwargs):
        print self
        print args
        print kwargs

    django_curry1 = django_functional.curry(_proxy_method, foo='bar')

    # REVIEW: Cannot mix args and unbound methods.
    # But curry() isn't a publicly documented method, and Django itself never
    # mixes the two.
    django_curry2 = django_functional.curry(_proxy_method, 17, foo='bar')

    # FAIL. This doesn't work.
    python_partial1 = functools.partial(_proxy_method, 17, foo='bar')

    # This works.
    def python_partial2(self, *args, **kwargs):
        return functools.partial(self._proxy_method, 17, foo='bar')(*args, **kwargs)

    # But then you might as well do this.
    def python_partial3(self, *args, **kwargs):
        return self._proxy_method(17, foo='bar', *args, **kwargs)


    # Check out self.__dict__ before and after accessing self.cached_property.
    @django_functional.cached_property
    def cached_property(self):
        return ', '.join(itertools.imap(unicode, xrange(100)))

    def _get_property(self):
        return "property"

    python_property = property(_get_property)
    django_property = django_functional.lazy_property(_get_property)


class Subclass(DjangoFunctionalUtils):
    # Compare python_property with django_property.
    def _get_property(self):
        return "subclass {}".format(super(Subclass, self)._get_property())

def my_lazy(resultclasses, func):
    return django_functional.lazy(func, *resultclasses)

def my_lazy_decorator(*resultclasses):
    return django_functional.curry(my_lazy, resultclasses)

lazy_integer_decorator = my_lazy_decorator(int)

def my_allow_lazy(resultclasses, func):
    return django_functional.allow_lazy(func, *resultclasses)

def my_allow_lazy_decorator(*resultclasses):
    return django_functional.curry(my_allow_lazy, resultclasses)

allow_lazy_integer_decorator = my_allow_lazy_decorator(int)

@lazy_integer_decorator
def lazy_int_identity(n):
    return n

@lazy_integer_decorator
def lazy_factorial(n):
    fact = 1
    for i in range(1, n+1):
        fact *= i
    return fact

# Try calling this with combinations of int and int Promise
@allow_lazy_integer_decorator
def possibly_lazy_multiply(m, n):
    return m * n
