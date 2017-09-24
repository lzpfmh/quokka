# from flask_admin.helpers import get_form_data
import datetime as dt
import pymongo
from flask import current_app
from quokka.admin.forms import ValidationError
from quokka.admin.views import ModelView
from quokka.core.auth import get_current_user
from quokka.utils.routing import get_content_url
from quokka.utils.text import slugify

from .formats import CreateForm, get_format


class AdminContentView(ModelView):
    """Base form for all contents"""
    base_query = {}
    base_defaults = {}

    details_modal = True
    can_view_details = True
    # create_modal = False
    # can_export = True
    # export_types = ['csv', 'json', 'yaml', 'html', 'xls']

    # details_modal_template = 'admin/model/modals/details.html'
    # create_template = 'admin/model/create.html'

    # edit_template = 'admin/quokka/edit.html'
    # EDIT template is taken from content_format

    page_size = 20
    can_set_page_size = True

    form = CreateForm
    column_list = (
        'title',
        'category',
        'authors',
        'date',
        'modified',
        'language',
        'published'
    )

    column_sortable_list = (
        'title',
        'category',
        'authors',
        'date',
        'modified',
        'language',
        'published'
    )
    column_default_sort = ('date', True)

    # TODO: implement scaffold_list_form in base class to enable below
    # column_editable_list = ['category', 'published', 'title']

    column_details_list = [
        'title',
        'category',
        'slug',
        'content_format',
        'content_type',
        'language',
        'date',
        'created_by',
        'modified',
        'modified_by',
        'version',
        '_isclone',
        'quokka_module',
        'quokka_format_module',
        'quokka_format_class',
        'quokka_create_form_module',
        'quokka_create_form_class'
    ]

    # column_export_list = []
    # column_formatters_export
    # column_formatters = {fieldname: callable} - view, context, model, name

    # column_extra_row_actions = None
    """
        List of row actions (instances of :class:`~flask_admin.model.template.
        BaseListRowAction`).

        Flask-Admin will generate standard per-row actions (edit, delete, etc)
        and will append custom actions from this list right after them.

        For example::

            from flask_admin.model.template import EndpointLinkRowAction,
            LinkRowAction

            class MyModelView(BaseModelView):
                column_extra_row_actions = [
                    LinkRowAction('glyphicon glyphicon-off',
                    'http://direct.link/?id={row_id}'),
                    EndpointLinkRowAction('glyphicon glyphicon-test',
                    'my_view.index_view')
                ]
    """

    # form_edit_rules / form_create_rules
    # form_rules = [
    #     # Define field set with header text and four fields
    #     rules.FieldSet(('title', 'category', 'tags'), 'Base'),
    #     # ... and it is just shortcut for:
    #     rules.Header('Content Type'),
    #     rules.Field('summary'),
    #     rules.Field('date'),
    #     # ...
    #     # It is possible to create custom rule blocks:
    #     # MyBlock('Hello World'),
    #     # It is possible to call macros from current context
    #     # rules.Macro('my_macro', foobar='baz')
    # ]

    # def create_form(self):
    #     form = super(ContentView, self).create_form()
    #     form.content_type.choices = [('a', 'a'), ('b', 'b')]
    #     return form

    # @property
    # def extra_js(self):
    #     return [
    #         url_for('static', filename='js/quokka_admin.js')
    #     ]

    def edit_form(self, obj):
        content_format = get_format(obj)
        self.edit_template = content_format.get_edit_template(
            obj
        ) or self.edit_template
        self.form_edit_rules = content_format.get_form_rules()
        self._refresh_form_rules_cache()
        form = content_format.get_edit_form(obj)
        return form

    def on_form_prefill(self, form, id):
        """Fill edit form with versioned data"""
        form.content.data = current_app.db.pull_content(id)

    def get_save_return_url(self, model, is_created):
        if is_created:
            return self.get_url('.edit_view', id=model['_id'])
        return super(AdminContentView, self).get_save_return_url(model,
                                                                 is_created)

    def on_model_change(self, form, model, is_created):

        if is_created:
            # each custom module should be identified by admin and format class
            self.add_module_metadata(model)

        get_format(model).before_save(form, model, is_created)

        if not model.get('slug'):
            model['slug'] = slugify(model['title'])

        existent = current_app.db.get('index', {'slug': model['slug'],
                                                'category': model['category']})

        if (is_created and existent) or (
                existent and existent['_id'] != model['_id']):
            raise ValidationError(f'{get_content_url(model)} already exists')

        now = dt.datetime.now()
        current_user = get_current_user()

        if is_created:
            # this defaults are also applied for cloning action

            # SIGNATURE
            model['_id'] = current_app.db.generate_id()
            model['date'] = now
            model['created_by'] = current_user
            model['published'] = False
            model['modified'] = None
            model['modified_by'] = None

            # DEFAULTS
            default_locale = current_app.config.get(
                'BABEL_DEFAULT_LOCALE', 'en'
            )
            model['language'] = self.base_query.get('language', default_locale)
            model['content_type'] = self.base_query.get(
                'content_type', 'article'
            )
            # subclasses can define attribute or property `base_defaults`
            # which returns a dict
            model.update(self.base_defaults)

        model['modified'] = now
        model['modified_by'] = current_user

        model.pop('csrf_token', None)

        current_app.db.push_content(model)

    def after_model_change(self, form, model, is_created):
        get_format(model).after_save(form, model, is_created)

    def add_module_metadata(self, model):
        quokka_format = get_format(model)
        form = getattr(self.__class__, 'form', self.get_form())
        model['quokka_module'] = self.__module__
        model['quokka_format_module'] = quokka_format.__module__
        model['quokka_format_class'] = quokka_format.__class__.__name__
        model['quokka_create_form_module'] = form.__module__
        model['quokka_create_form_class'] = form.__class__.__name__

    def get_list(self, page, sort_column, sort_desc, search, filters,
                 execute=True, page_size=None):
        """
            Get list of objects from TinyDB
            :param page:
                Page number
            :param sort_column:
                Sort column
            :param sort_desc:
                Sort descending
            :param search:
                Search criteria
            :param filters:
                List of applied fiters
            :param execute:
                Run query immediately or not
            :param page_size:
                Number of results. Defaults to ModelView's page_size. Can be
                overriden to change the page_size limit. Removing the page_size
                limit requires setting page_size to 0 or False.
        """
        query = {**self.base_query}

        # Filters
        if self._filters:
            data = []

            for flt, flt_name, value in filters:
                f = self._filters[flt]
                data = f.apply(data, f.clean(value))

            if data:
                if len(data) == 1:
                    query = data[0]
                else:
                    query['$and'] = data

        # Search
        if self._search_supported and search:
            query = self._search(query, search)

        # Get count
        count = self.coll.find(
            query).count() if not self.simple_list_pager else None

        # Sorting
        sort_by = None

        if sort_column:
            sort_by = [(sort_column, pymongo.DESCENDING
                        if sort_desc else pymongo.ASCENDING)]
        else:
            order = self._get_default_order()

            if order:
                sort_by = [(order[0], pymongo.DESCENDING
                            if order[1] else pymongo.ASCENDING)]

        # Pagination
        if page_size is None:
            page_size = self.page_size

        skip = 0

        if page and page_size:
            skip = page * page_size

        results = self.coll.find(
            query, sort=sort_by, skip=skip, limit=page_size)

        if execute:
            results = list(results)

        return count, results

    def get_one(self, id):
        """
            Return single model instance by ID
            :param id:
                Model ID
        """
        query = {**self.base_query}
        query['_id'] = self._get_valid_id(id)
        return self.coll.find_one(query)


class AdminArticlesView(AdminContentView):
    """Only articles"""
    base_query = {'content_type': 'article'}


class AdminPagesView(AdminContentView):
    """Only pages"""
    base_query = {'content_type': 'page'}
