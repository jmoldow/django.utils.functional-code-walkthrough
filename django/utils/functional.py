import copy
import operator
from functools import wraps, total_ordering
import sys
import warnings

import six


# QUESTION: What does functools.partial(...) do?
# ANSWER: It returns an object of type functools.partial. It is a constructor,
# not a function. And the returned values are (callable) objects, but NOT
# functions.

# You can't trivially replace this with `functools.partial` because this binds
# to classes and returns bound instances, whereas functools.partial (on
# CPython) is a type and its instances don't bind.
def curry(_curried_func, *args, **kwargs):
    def _curried(*moreargs, **morekwargs):
        return _curried_func(*(args + moreargs), **dict(kwargs, **morekwargs))
    return _curried


class cached_property(object):
    """
    Decorator that converts a method with a single self argument into a
    property cached on the instance.
    """
    def __init__(self, func):
        self.func = func

    # QUESTION: Remember what a descriptor does / how __get__ works?
    # ANSWER: A descriptor is any object with a __get__ method (or a __set__
    # method, or a __delete__ method).
    # If a class attribute (NOT an instance attribute) is set equal to an
    # instance of a descriptor, then gets / sets / deletes of that attribute
    # will be proxied through __get__ / __set__ / __delete__, respectively.
    # Example:
    #   class Descriptor(object):
    #     def __get__(self, obj, type=None):
    #       print (self, obj, type)
    #     def __set__(self, obj, value):
    #       print (self, obj, value)
    #     def __delete__(self, obj):
    #       print (self, obj)
    #   descriptor = Descriptor()
    #   class Foo(object):
    #     bar = descriptor
    #   foo = Foo()
    # ``Foo.bar`` is equivalent to ``descriptor.__get__(None, Foo)``
    # ``foo.bar`` is equivalent to ``descriptor.__get__(foo, Foo)``
    # ``foo.bar = value`` is equivalent to ``descriptor.__set__(foo, value)``
    # ``del foo.bar`` is equivalent to ``descriptor.__delete__(foo)``
    # All methods are descriptors. If bar is a method on class Foo with
    # instance foo, then foo.bar does not refer to the original function, but
    # rather a bound method object constructed and returned by
    # function.__get__. When the bound method is called, it automatically
    # passes the object it is bound to as the self argument to the original,
    # unbound method.
    # Properties are also descriptors. This is how foo.property can trigger a
    # method call. It is because ``foo.bar`` is actually
    # Foo.__dict__['bar'].__get__(foo, Foo), which calls fget with foo as self.
    def __get__(self, instance, type=None):
        if instance is None:
            return self
        # REVIEW: Compute the result, then store it, overwriting the
        # cached_property object and leaving behind the permanent result.
        res = instance.__dict__[self.func.__name__] = self.func(instance)
        return res


# REVIEW: Not nearly as feature-ful as aplus promises, or as python futures.
# But it does have unique features of its own. Unlike those two classes,
# objects of type Promise use object proxying to make the Promise nearly
# indistinguishable from the underlying object (whereas in those two classes,
# you must extract or map on the value).
# REVIEW: If this is meant to be a dummy class, perhaps Django shouldn't be
# doing anything other than isinstance(obj, Promise) in code outside this
# module. Otherwise, the public methods should be documented on the public base
# class. But Promise is not publicly documented for external use.
class Promise(object):
    """
    This is just a base class for the proxy class created in
    the closure of the lazy function. It can be used to recognize
    promises in code.
    """
    pass


# REVIEW: This is a higher-order function. It accepts a function, and returns
# another function. It does not return an object. So the result relies on a
# closure to remember the values of func and resultclasses, so that they can be
# used in the implementations of various methods of the private __proxy__
# class.
# REVIEW: If resultclasses were a list instead of var-args, you could reverse
# the order of the arguments (def lazy(resultclasses, func)) and then use
# curry() to create a decorator.
# REVIEW: Why no memoizing? I don't know, can't find any explantion in the
# comments, git logs, or bug tracker.
def lazy(func, *resultclasses):
    """
    Turns any callable into a lazy evaluated callable. You need to give result
    classes or types -- at least one is needed so that the automatic forcing of
    the lazy evaluation code is triggered. Results are not memoized; the
    function is evaluated on every access.
    """

    # QUESTION: Who knows what @total_ordering does?
    # ANSWER: From the Python documentation:
    """
    functools.total_ordering(cls)
    Given a class defining one or more rich comparison ordering methods, this
    class decorator supplies the rest. This simplifies the effort involved in
    specifying all of the possible rich comparison operations.
    The class must define one of __lt__(), __le__(), __gt__(), or __ge__(). In
    addition, the class should supply an __eq__() method.
    """
    @total_ordering
    class __proxy__(Promise):
        """
        Encapsulate a function call and act as a proxy for methods that are
        called on the result of that function. The function is not evaluated
        until one of the methods on the result is called.
        """
        __dispatch = None

        def __init__(self, args, kw):
            self.__args = args
            self.__kw = kw
            # REVIEW: Why is this check necessary? __proxy__ is only used in
            # __wrapper__, and it is immediately initialized. There is no point
            # when __proxy__.__dispatch (the class attribute) is ever anything
            # but None, so this condition should always be True.
            if self.__dispatch is None:
                self.__prepare_class__()

        @classmethod
        def __prepare_class__(cls):
            # REVIEW: __dispatch is a mapping from resultclasses, to
            # method_name -> method_object mappings.
            cls.__dispatch = {}
            for resultclass in resultclasses:
                cls.__dispatch[resultclass] = {}
                # QUESTION: What is mro()? Why reversed?
                # ANSWER: mro stands for method resolution order. When you have
                # polymorphism and Python needs to decide which definition of
                # an attribute or method to use, Python will search through the
                # mro and pick the first one it finds. With single inheritance,
                # mro goes from subclass to base class. With multiple
                # inheritance it is more complicated. When filling out the
                # dispatch table, we use reverse() to mimic the behavior of
                # subclass definitions shadowing baseclass definitions.
                for type_ in reversed(resultclass.mro()):
                    for (k, v) in type_.__dict__.items():
                        # All __promise__ return the same wrapper method, but
                        # they also do setup, inserting the method into the
                        # dispatch dict.
                        # REVIEW: This is an important explanation that should
                        # also be on the docstring for __promise__.
                        # REVIEW: This line is tricky. Note that it is called
                        # with resultclass, NOT type_.
                        meth = cls.__promise__(resultclass, k, v)
                        if hasattr(cls, k):
                            # REVIEW: This was confusing at first. Why would
                            # you set for the highest ancestor, and ignore
                            # overrides? Turns out that meth is the same for
                            # all overrides, the only thing that matters is the
                            # name. And __promise__ gets called for all
                            # overrides, and that sets the relevant state that
                            # meth needs.
                            continue
                        setattr(cls, k, meth)
            # REVIEW: The six module is used for python2 / python3
            # compatibility. Because of the breaking change to text types in
            # python3 and the incompatibility (in both python2 and python3)
            # between bytes and text, special code is needed here, and text and
            # bytes can't be mixed. This code is important to Django, because
            # one of the main uses of lazy() is for lazy translations.
            cls._delegate_bytes = bytes in resultclasses
            cls._delegate_text = six.text_type in resultclasses
            assert not (cls._delegate_bytes and cls._delegate_text), "Cannot call lazy() with both bytes and text return types."
            if cls._delegate_text:
                if six.PY3:
                    cls.__str__ = cls.__text_cast
                else:
                    cls.__unicode__ = cls.__text_cast
            elif cls._delegate_bytes:
                if six.PY3:
                    cls.__bytes__ = cls.__bytes_cast
                else:
                    cls.__str__ = cls.__bytes_cast

        # REVIEW: lazy_function(*__args, **__kw) returns a __proxy__ / Promise
        # object. lazy_function(*__args, **__kw).method is the __wrapper__
        # below. lazy_function(*__args, **__kw).method(*args, **kwargs)
        # evaluates function(*__args, **__kw), then passes it as self to the
        # wrapped method (which is stored in __dispatch).
        @classmethod
        def __promise__(cls, klass, funcname, method):
            # Builds a wrapper around some magic method and registers that
            # magic method for the given type and method name.
            def __wrapper__(self, *args, **kw):
                # Automatically triggers the evaluation of a lazy value and
                # applies the given magic method of the result type.
                # REVIEW: Only funcname is used in here. klass and method are
                # only used outside the definition for __wrapper__.
                res = func(*self.__args, **self.__kw)
                # REVIEW: Iterate forward through the mro(), so we get the
                # correct method override.
                for t in type(res).mro():
                    # REVIEW: We only care about classes in resultclasses /
                    # self.__dispatch.
                    if t in self.__dispatch:
                        # REVIEW: Remember: the only things in __dispatch are
                        # the resultclasses, and they have items for each
                        # method on each superclass. So funcname will never be
                        # missing.
                        return self.__dispatch[t][funcname](res, *args, **kw)
                raise TypeError("Lazy object returned unexpected type.")

            # REVIEW: This state gets set even if the __wrapper__ is discarded
            # by the caller.
            if klass not in cls.__dispatch:
                cls.__dispatch[klass] = {}
            # REVIEW: klass is one of the resultclasses, but method isn't
            # necessarily a method on klass, it may be a method on a
            # superclass.
            # REVIEW: In __prepare_class__, we loop through klass.mro() in
            # reverse order, so at the end, the correct method override will be
            # stored here.
            cls.__dispatch[klass][funcname] = method
            return __wrapper__

        def __text_cast(self):
            return func(*self.__args, **self.__kw)

        def __bytes_cast(self):
            return bytes(func(*self.__args, **self.__kw))

        # QUESTION: What does leading double-underscores in a method name do?
        # ANSWER: It is the closest thing to a private method that Python has.
        # For anything outside the class definition, the attribute is mangled
        # to something else. Though, if you know how the mangling works, you
        # can still call the method.
        # REVIEW: Should this be non-private? Should it be documented on the
        # base Promise class? In a different module, Django calls the mangled
        # method name...
        def __cast(self):
            if self._delegate_bytes:
                return self.__bytes_cast()
            elif self._delegate_text:
                return self.__text_cast()
            else:
                return func(*self.__args, **self.__kw)

        def __ne__(self, other):
            if isinstance(other, Promise):
                other = other.__cast()
            return self.__cast() != other

        def __eq__(self, other):
            if isinstance(other, Promise):
                other = other.__cast()
            return self.__cast() == other

        def __lt__(self, other):
            if isinstance(other, Promise):
                other = other.__cast()
            return self.__cast() < other

        def __hash__(self):
            return hash(self.__cast())

        def __mod__(self, rhs):
            if self._delegate_bytes and six.PY2:
                return bytes(self) % rhs
            elif self._delegate_text:
                return six.text_type(self) % rhs
            return self.__cast() % rhs

        def __deepcopy__(self, memo):
            # Instances of this class are effectively immutable. It's just a
            # collection of functions. So we don't need to do anything
            # complicated for copying.
            memo[id(self)] = self
            return self

    @wraps(func)
    # REVIEW: This is the result of the higher-order lazy() function. Calls to
    # the lazily-evaluated function are actually calls to __wrapper__. Calling
    # the function instantiates a __proxy__ (subclass of Promise) object, which
    # is a proxy to the result object, which we assert to have a type in the
    # list resultclasses. The result object is what we get after calling func
    # with *args and **kw.
    def __wrapper__(*args, **kw):
        # Creates the proxy object, instead of the actual value.
        return __proxy__(args, kw)

    return __wrapper__


def allow_lazy(func, *resultclasses):
    """
    A decorator that allows a function to be called with one or more lazy
    arguments. If none of the args are lazy, the function is evaluated
    immediately, otherwise a __proxy__ is returned that will evaluate the
    function when needed.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # REVIEW: for/else control flow...
        for arg in list(args) + list(six.itervalues(kwargs)):
            if isinstance(arg, Promise):
                break
        else:
            return func(*args, **kwargs)
        # REVIEW: If any argument is a Promise, further delay execution by
        # constructing the lazy version of func, and then using that to return
        # a new Promise for func(*args, **kwargs).
        return lazy(func, *resultclasses)(*args, **kwargs)
    return wrapper

empty = object()


# REVIEW: Used in the definition of LazyObject. Calls the wrapped function, but
# calls _setup() first if it hasn't already been called.
# When proxy.method() is called, the call is proxied to the underlying object.
def new_method_proxy(func):
    # REVIEW: Forgot to use @functools.wraps()?
    # REVIEW: Why aren't kwargs allowed? Probably because this is only used on
    # build-in Python magic methods, which don't accept kwargs. But then this
    # should be specified in the documentation.
    def inner(self, *args):
        if self._wrapped is empty:
            self._setup()
        # REVIEW: self._wrapped is the proxied object, is passed as self.
        return func(self._wrapped, *args)
    return inner


class LazyObject(object):
    """
    A wrapper for another class that can be used to delay instantiation of the
    wrapped class.

    By subclassing, you have the opportunity to intercept and alter the
    instantiation. If you don't need to do that, use SimpleLazyObject.
    """

    # Avoid infinite recursion when tracing __init__ (#19456).
    _wrapped = None

    def __init__(self):
        self._wrapped = empty

    # QUESTION: Remember the difference between __getattribute__ and __getattr__? :)
    # ANSWER: __getattribute__ is what gets called when you try to access an
    # attribute on an object.  If it fails to find anything in __dict__ and in
    # superclasses, as a last resort it calls __getattr__.
    # REVIEW: Proxy most requests for attributes to the underlying wrapped object.
    __getattr__ = new_method_proxy(getattr)

    def __setattr__(self, name, value):
        if name == "_wrapped":
            # Assign to __dict__ to avoid infinite __setattr__ loops.
            self.__dict__["_wrapped"] = value
        else:
            if self._wrapped is empty:
                self._setup()
            setattr(self._wrapped, name, value)

    def __delattr__(self, name):
        if name == "_wrapped":
            raise TypeError("can't delete _wrapped.")
        if self._wrapped is empty:
            self._setup()
        delattr(self._wrapped, name)

    def _setup(self):
        """
        Must be implemented by subclasses to initialize the wrapped object.
        """
        raise NotImplementedError('subclasses of LazyObject must provide a _setup() method')

    if six.PY3:
        __bytes__ = new_method_proxy(bytes)
        __str__ = new_method_proxy(str)
        __bool__ = new_method_proxy(bool)
    else:
        __str__ = new_method_proxy(str)
        __unicode__ = new_method_proxy(unicode)
        __nonzero__ = new_method_proxy(bool)

    # Introspection support
    __dir__ = new_method_proxy(dir)

    # Need to pretend to be the wrapped class, for the sake of objects that
    # care about this (especially in equality tests)
    # REVIEW: The operator module has a lot of useful stuff in it!
    # This is easier than writing
    # property(new_method_proxy(lambda self: getattr(self, "__class__")))
    # or even
    # @property
    # @new_method_proxy
    # def __class__(self):
    #     return self.__class__
    __class__ = property(new_method_proxy(operator.attrgetter("__class__")))
    __eq__ = new_method_proxy(operator.eq)
    __ne__ = new_method_proxy(operator.ne)
    __hash__ = new_method_proxy(hash)

    # Dictionary methods support
    __getitem__ = new_method_proxy(operator.getitem)
    __setitem__ = new_method_proxy(operator.setitem)
    __delitem__ = new_method_proxy(operator.delitem)

    __len__ = new_method_proxy(len)
    __contains__ = new_method_proxy(operator.contains)


# Workaround for http://bugs.python.org/issue12370
_super = super


class SimpleLazyObject(LazyObject):
    """
    A lazy object initialized from any function.

    Designed for compound objects of unknown type. For builtins or objects of
    known type, use django.utils.functional.lazy.
    """
    def __init__(self, func):
        """
        Pass in a callable that returns the object to be wrapped.

        If copies are made of the resulting SimpleLazyObject, which can happen
        in various circumstances within Django, then you must ensure that the
        callable can be safely run more than once and will return the same
        value.
        """
        self.__dict__['_setupfunc'] = func
        _super(SimpleLazyObject, self).__init__()

    def _setup(self):
        self._wrapped = self._setupfunc()

    # Return a meaningful representation of the lazy object for debugging
    # without evaluating the wrapped object.
    def __repr__(self):
        if self._wrapped is empty:
            repr_attr = self._setupfunc
        else:
            repr_attr = self._wrapped
        return '<%s: %r>' % (type(self).__name__, repr_attr)

    def __deepcopy__(self, memo):
        if self._wrapped is empty:
            # We have to use SimpleLazyObject, not self.__class__, because the
            # latter is proxied.
            result = SimpleLazyObject(self._setupfunc)
            memo[id(self)] = result
            return result
        return copy.deepcopy(self._wrapped, memo)


# QUESTION: What happens when, in a subclass, you override the fget method for
# a baseclass property, without redefining the property itself?
# ANSWER: A property is a built-in descriptor type. ``foo.property`` is
# actually ``type(foo).__dict__['property'].__get__(foo, type(foo))``, and the
# implementation of __get__ calls the fget function that was originally passed
# to the property() constructor. So even if fget is redefined in a subclass,
# the property object still holds a reference to the fget in the base class, so
# the property will behave exactly the same when referenced in the subclass,
# even though you probably wanted to change the implementation by redefining
# fget. You'll need to also redefine the property itself, or use the
# below-defined lazy_property instead of the built-in property.

# REVIEW: lazy_property is not a completely accurate name for this, and is
# actually quite confusing. Still, I can see what the authors mean by this.
# They mean that the fget / fset / fdel methods are not chosen at class
# definition time, but rather are chosen at runtime, depending on what classes
# in the MRO have overriden fget / fset / fdel.
# REVIEW: If you were to do:
#     class Foo(object):
#         def _get_bar(self):
#             return "bar"
#         bar = property(_get_bar)
# and wanted to override _get_bar in a subclass, then you would also need to
# override bar in the subclass definition, if you wanted it to keep working
# correctly. lazy_property is lazy in the sense that it defers choosing which
# functions to call until runtime. This allows it to choose the correct
# subclass implementation by name. So if property() were replaced above with
# lazy_property(), then the following subclass would still have the bar
# property correctly defined.
#     class FooSubclass(Foo):
#         def _get_bar(self):
#             return "subclass bar"
class lazy_property(property):
    """
    A property that works with subclasses by wrapping the decorated
    functions of the base class.
    """
    def __new__(cls, fget=None, fset=None, fdel=None, doc=None):
        if fget is not None:
            @wraps(fget)
            # REVIEW: This is passed as a default argument value, for an
            # argument that will never be passed. Why not just use
            # fget.__name__ directly? Does putting it as a default argument
            # value allow Python to not have to use a closure?
            def fget(instance, instance_type=None, name=fget.__name__):
                return getattr(instance, name)()
        if fset is not None:
            @wraps(fset)
            def fset(instance, value, name=fset.__name__):
                return getattr(instance, name)(value)
        if fdel is not None:
            @wraps(fdel)
            def fdel(instance, name=fdel.__name__):
                return getattr(instance, name)()
        return property(fget, fset, fdel, doc)


def partition(predicate, values):
    """
    Splits the values into two sets, based on the return value of the function
    (True/False). e.g.:

        >>> partition(lambda x: x > 3, range(5))
        [0, 1, 2, 3], [4]
    """
    results = ([], [])
    for item in values:
        results[predicate(item)].append(item)
    return results
# REVIEW: Why not bucket on any function get_bucket? e.g.
"""
def bucket(get_bucket, values):
    results = defaultdict(list)
    for item in values:
        results[get_bucket(values)].append(item)
    return results

def partition(predicate, values):
    buckets = bucket(predicate, values)
    return (buckets[False], buckets[True])
"""
