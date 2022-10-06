"""Main routing table for GN2"""
import array
import base64
import csv
import datetime
import flask
import io  # Todo: Use cStringIO?

import json
import numpy as np
import os
import pickle as pickle
import random
import sys
import traceback
import uuid
import xlsxwriter

from zipfile import ZipFile
from zipfile import ZIP_DEFLATED

from wqflask import app

from gn3.computations.gemma import generate_hash_of_string
from flask import current_app
from flask import g
from flask import Response
from flask import request
from flask import make_response
from flask import render_template
from flask import send_from_directory
from flask import redirect
from flask import send_file

# Some of these (like collect) might contain endpoints, so they're still used.
# Blueprints should probably be used instead.
from wqflask import collect
from wqflask import search_results
from wqflask import server_side
from base.data_set import create_dataset  # Used by YAML in marker_regression
from wqflask.show_trait import show_trait
from wqflask.show_trait import export_trait_data
from wqflask.show_trait.show_trait import get_diff_of_vals
from wqflask.heatmap import heatmap
from wqflask.external_tools import send_to_bnw
from wqflask.external_tools import send_to_webgestalt
from wqflask.external_tools import send_to_geneweaver
from wqflask.comparison_bar_chart import comparison_bar_chart
from wqflask.marker_regression import run_mapping
from wqflask.marker_regression.exceptions import NoMappingResultsError
from wqflask.marker_regression import display_mapping_results
from wqflask.network_graph import network_graph
from wqflask.correlation.show_corr_results import set_template_vars
from wqflask.correlation.correlation_gn3_api import compute_correlation
from wqflask.correlation.rust_correlation import compute_correlation_rust
from wqflask.correlation_matrix import show_corr_matrix
from wqflask.correlation import corr_scatter_plot
from wqflask.correlation.exceptions import WrongCorrelationType
from wqflask.ctl.gn3_ctl_analysis import run_ctl

from wqflask.wgcna.gn3_wgcna import run_wgcna
from wqflask.snp_browser import snp_browser
from wqflask.search_results import SearchResultPage
from wqflask.export_traits import export_traits
from wqflask.gsearch import GSearch
from wqflask.update_search_results import GSearch as UpdateGSearch
from wqflask.docs import Docs, update_text
from wqflask.decorators import edit_access_required
from wqflask.db_info import InfoPage

from utility import temp_data
from utility.tools import TEMPDIR
from utility.tools import USE_REDIS
from utility.tools import GN_SERVER_URL
from utility.tools import GN_VERSION
from utility.tools import JS_TWITTER_POST_FETCHER_PATH
from utility.tools import JS_GUIX_PATH
from utility.helper_functions import get_species_groups
from utility.redis_tools import get_redis_conn


from base.webqtlConfig import GENERATED_IMAGE_DIR

from wqflask.database import database_connection


Redis = get_redis_conn()


@app.errorhandler(Exception)
def handle_generic_exceptions(e):
    import werkzeug
    err_msg = str(e)
    now = datetime.datetime.utcnow()
    time_str = now.strftime('%l:%M%p UTC %b %d, %Y')
    # get the stack trace and send it to the logger
    exc_type, exc_value, exc_traceback = sys.exc_info()
    formatted_lines = (f"{request.url} ({time_str}) \n"
                       f"{traceback.format_exc()}")
    _message_templates = {
        werkzeug.exceptions.NotFound: ("404: Not Found: "
                                       f"{time_str}: {request.url}"),
        werkzeug.exceptions.BadRequest: ("400: Bad Request: "
                                         f"{time_str}: {request.url}"),
        werkzeug.exceptions.RequestTimeout: ("408: Request Timeout: "
                                             f"{time_str}: {request.url}")}
    # Default to the lengthy stack trace!
    app.logger.error(_message_templates.get(exc_type,
                                            formatted_lines))
    # Handle random animations
    # Use a cookie to have one animation on refresh
    animation = request.cookies.get(err_msg[:32])
    if not animation:
        animation = random.choice([fn for fn in os.listdir(
            "./wqflask/static/gif/error") if fn.endswith(".gif")])

    resp = make_response(render_template("error.html", message=err_msg,
                                         stack={formatted_lines},
                                         error_image=animation,
                                         version=GN_VERSION))
    resp.set_cookie(err_msg[:32], animation)
    return resp


@app.route("/authentication_needed")
def no_access_page():
    return render_template("new_security/not_authenticated.html")


@app.route("/")
def index_page():
    params = request.args
    if 'import_collections' in params:
        import_collections = params['import_collections']
        if import_collections == "true":
            g.user_session.import_traits_to_user(params['anon_id'])
    return render_template(
        "index_page.html", version=GN_VERSION, gn_server_url=GN_SERVER_URL)


@app.route("/tmp/<img_path>")
def tmp_page(img_path):
    initial_start_vars = request.form
    imgfile = open(GENERATED_IMAGE_DIR + img_path, 'rb')
    imgdata = imgfile.read()
    imgB64 = base64.b64encode(imgdata)
    bytesarray = array.array('B', imgB64)
    return render_template("show_image.html",
                           img_base64=bytesarray)


@app.route("/js/<path:filename>")
def js(filename):
    js_path = JS_GUIX_PATH
    name = filename
    if 'js_alt/' in filename:
        js_path = js_path.replace('genenetwork2/javascript', 'javascript')
        name = name.replace('js_alt/', '')
    return send_from_directory(js_path, name)


@app.route("/css/<path:filename>")
def css(filename):
    js_path = JS_GUIX_PATH
    name = filename
    if 'js_alt/' in filename:
        js_path = js_path.replace('genenetwork2/javascript', 'javascript')
        name = name.replace('js_alt/', '')
    return send_from_directory(js_path, name)


@app.route("/twitter/<path:filename>")
def twitter(filename):
    return send_from_directory(JS_TWITTER_POST_FETCHER_PATH, filename)


@app.route("/search", methods=('GET',))
def search_page():
    result = None
    if USE_REDIS:
        key = "search_results:v1:" + \
            json.dumps(request.args, sort_keys=True)
        result = Redis.get(key)
        if result:
            result = pickle.loads(result)
    result = SearchResultPage(request.args).__dict__
    valid_search = result['search_term_exists']
    if USE_REDIS and valid_search:
        # Redis.set(key, pickle.dumps(result, pickle.HIGHEST_PROTOCOL))
        Redis.expire(key, 60 * 60)

    if valid_search:
        return render_template("search_result_page.html", **result)
    else:
        return render_template("search_error.html")


@app.route("/search_table", methods=('GET',))
def search_page_table():
    the_search = search_results.SearchResultPage(request.args)
    current_page = server_side.ServerSideTable(
        len(the_search.trait_list),
        the_search.trait_list,
        the_search.header_data_names,
        request.args,
    ).get_page()

    return flask.jsonify(current_page)


@app.route("/gsearch", methods=('GET',))
def gsearchact():
    result = GSearch(request.args).__dict__
    type = request.args['type']
    if type == "gene":
        return render_template("gsearch_gene.html", **result)
    elif type == "phenotype":
        return render_template("gsearch_pheno.html", **result)


@app.route("/gsearch_table", methods=('GET',))
def gsearchtable():
    gsearch_table_data = GSearch(request.args)
    current_page = server_side.ServerSideTable(
        gsearch_table_data.trait_count,
        gsearch_table_data.trait_list,
        gsearch_table_data.header_data_names,
        request.args,
    ).get_page()

    return flask.jsonify(current_page)


@app.route("/gsearch_updating", methods=('POST',))
def gsearch_updating():
    result = UpdateGSearch(request.args).__dict__
    return result['results']


@app.route("/docedit")
def docedit():
    try:
        if g.user_session.record['user_email_address'] == "zachary.a.sloan@gmail.com" or g.user_session.record['user_email_address'] == "labwilliams@gmail.com":
            doc = Docs(request.args['entry'], request.args)
            return render_template("docedit.html", **doc.__dict__)
        else:
            return "You shouldn't be here!"
    except:
        return "You shouldn't be here!"


@app.route('/generated/<filename>')
def generated_file(filename):
    return send_from_directory(GENERATED_IMAGE_DIR, filename)


@app.route("/help")
def help():
    doc = Docs("help", request.args)
    return render_template("docs.html", **doc.__dict__)


@app.route("/wgcna_setup", methods=('POST',))
def wcgna_setup():
    # We are going to get additional user input for the analysis
    # Display them using the template
    return render_template("wgcna_setup.html", **request.form)


@app.route("/wgcna_results", methods=('POST',))
def wcgna_results():
    """call the gn3 api to get wgcna response data"""
    results = run_wgcna(dict(request.form))
    return render_template("gn3_wgcna_results.html", **results)


@app.route("/ctl_setup", methods=('POST',))
def ctl_setup():
    # We are going to get additional user input for the analysis
    # Display them using the template
    return render_template("ctl_setup.html", **request.form)


@app.route("/ctl_results", methods=["POST"])
def ctl_results():
    ctl_results = run_ctl(request.form)
    return render_template("gn3_ctl_results.html", **ctl_results)


@app.route("/ctl_network_files/<file_name>/<file_type>")
def fetch_network_files(file_name, file_type):
    file_path = f"{file_name}.{file_type}"

    file_path = os.path.join("/tmp/", file_path)

    return send_file(file_path)


@app.route("/intro")
def intro():
    doc = Docs("intro", request.args)
    return render_template("docs.html", **doc.__dict__)


@app.route("/tutorials")
def tutorials():
    return render_template("tutorials.html")


@app.route("/credits")
def credits():
    return render_template("credits.html")


@app.route("/update_text", methods=('POST',))
def update_page():
    update_text(request.form)
    doc = Docs(request.form['entry_type'], request.form)
    return render_template("docs.html", **doc.__dict__)


@app.route("/submit_trait")
def submit_trait_form():
    species_and_groups = get_species_groups()
    return render_template(
        "submit_trait.html",
        species_and_groups=species_and_groups,
        gn_server_url=GN_SERVER_URL,
        version=GN_VERSION)


@app.route("/create_temp_trait", methods=('POST',))
def create_temp_trait():
    doc = Docs("links")
    return render_template("links.html", **doc.__dict__)


@app.route('/export_trait_excel', methods=('POST',))
def export_trait_excel():
    """Excel file consisting of the sample data from the trait data and analysis page"""
    trait_name, sample_data = export_trait_data.export_sample_table(
        request.form)
    app.logger.info(request.url)
    buff = io.BytesIO()
    workbook = xlsxwriter.Workbook(buff, {'in_memory': True})
    worksheet = workbook.add_worksheet()
    for i, row in enumerate(sample_data):
        for j, column in enumerate(row):
            worksheet.write(i, j, row[j])
    workbook.close()
    excel_data = buff.getvalue()
    buff.close()

    return Response(excel_data,
                    mimetype='application/vnd.ms-excel',
                    headers={"Content-Disposition": "attachment;filename=" + trait_name + ".xlsx"})


@app.route('/export_trait_csv', methods=('POST',))
def export_trait_csv():
    """CSV file consisting of the sample data from the trait data and analysis page"""
    trait_name, sample_data = export_trait_data.export_sample_table(
        request.form)

    buff = io.StringIO()
    writer = csv.writer(buff)
    for row in sample_data:
        writer.writerow(row)
    csv_data = buff.getvalue()
    buff.close()

    return Response(csv_data,
                    mimetype='text/csv',
                    headers={"Content-Disposition": "attachment;filename=" + trait_name + ".csv"})


@app.route('/export_traits_csv', methods=('POST',))
def export_traits_csv():
    """CSV file consisting of the traits from the search result page"""
    file_list = export_traits(request.form, "metadata")

    if len(file_list) > 1:
        now = datetime.datetime.now()
        time_str = now.strftime('%H:%M_%d%B%Y')
        filename = "export_{}".format(time_str)
        memory_file = io.BytesIO()
        with ZipFile(memory_file, mode='w', compression=ZIP_DEFLATED) as zf:
            for the_file in file_list:
                zf.writestr(the_file[0], the_file[1])

        memory_file.seek(0)

        return send_file(memory_file, attachment_filename=filename + ".zip", as_attachment=True)
    else:
        return Response(file_list[0][1],
                        mimetype='text/csv',
                        headers={"Content-Disposition": "attachment;filename=" + file_list[0][0]})


@app.route('/export_collection', methods=('POST',))
def export_collection_csv():
    """CSV file consisting of trait list so collections can be exported/shared"""
    out_file = export_traits(request.form, "collection")
    return Response(out_file[1],
                    mimetype='text/csv',
                    headers={"Content-Disposition": "attachment;filename=" + out_file[0] + ".csv"})


@app.route('/export_perm_data', methods=('POST',))
def export_perm_data():
    """CSV file consisting of the permutation data for the mapping results"""
    perm_info = json.loads(request.form['perm_info'])

    now = datetime.datetime.now()
    time_str = now.strftime('%H:%M_%d%B%Y')

    file_name = "Permutation_" + \
        perm_info['num_perm'] + "_" + perm_info['trait_name'] + "_" + time_str

    the_rows = [
        ["#Permutation Test"],
        ["#File_name: " + file_name],
        ["#Metadata: From GeneNetwork.org"],
        ["#Trait_ID: " + perm_info['trait_name']],
        ["#Trait_description: " + perm_info['trait_description']],
        ["#N_permutations: " + str(perm_info['num_perm'])],
        ["#Cofactors: " + perm_info['cofactors']],
        ["#N_cases: " + str(perm_info['n_samples'])],
        ["#N_genotypes: " + str(perm_info['n_genotypes'])],
        ["#Genotype_file: " + perm_info['genofile']],
        ["#Units_linkage: " + perm_info['units_linkage']],
        ["#Permutation_stratified_by: "
            + ", ".join([str(cofactor) for cofactor in perm_info['strat_cofactors']])],
        ["#RESULTS_1: Suggestive LRS(p=0.63) = "
         + str(np.percentile(np.array(perm_info['perm_data']), 67))],
        ["#RESULTS_2: Significant LRS(p=0.05) = " + str(
            np.percentile(np.array(perm_info['perm_data']), 95))],
        ["#RESULTS_3: Highly Significant LRS(p=0.01) = " + str(
            np.percentile(np.array(perm_info['perm_data']), 99))],
        ["#Comment: Results sorted from low to high peak linkage"]
    ]

    buff = io.StringIO()
    writer = csv.writer(buff)
    writer.writerows(the_rows)
    for item in perm_info['perm_data']:
        writer.writerow([item])
    csv_data = buff.getvalue()
    buff.close()

    return Response(csv_data,
                    mimetype='text/csv',
                    headers={"Content-Disposition": "attachment;filename=" + file_name + ".csv"})


@app.route("/show_temp_trait", methods=('POST',))
def show_temp_trait_page():
    with database_connection() as conn, conn.cursor() as cursor:
        user_id = ((g.user_session.record.get(b"user_id") or b"").decode("utf-8")
                   or g.user_session.record.get("user_id") or "")
        template_vars = show_trait.ShowTrait(cursor,
                                             user_id=user_id,
                                             kw=request.form)
        template_vars.js_data = json.dumps(template_vars.js_data,
                                           default=json_default_handler,
                                           indent="   ")
        return render_template("show_trait.html", **template_vars.__dict__)


@app.route("/show_trait")
def show_trait_page():
    with database_connection() as conn, conn.cursor() as cursor:
        user_id = ((g.user_session.record.get(b"user_id") or b"").decode("utf-8")
                   or g.user_session.record.get("user_id") or "")
        template_vars = show_trait.ShowTrait(cursor,
                                             user_id=user_id,
                                             kw=request.args)
        template_vars.js_data = json.dumps(template_vars.js_data,
                                           default=json_default_handler,
                                           indent="   ")
        return render_template("show_trait.html", **template_vars.__dict__)


@app.route("/heatmap", methods=('POST',))
def heatmap_page():
    start_vars = request.form
    temp_uuid = uuid.uuid4()

    traits = [trait.strip() for trait in start_vars['trait_list'].split(',')]
    with database_connection() as conn, conn.cursor() as cursor:
        if traits[0] != "":
            version = "v5"
            key = "heatmap:{}:".format(
                version) + json.dumps(start_vars, sort_keys=True)
            result = Redis.get(key)

            if result:
                result = pickle.loads(result)

            else:
                template_vars = heatmap.Heatmap(cursor, request.form, temp_uuid)
                template_vars.js_data = json.dumps(template_vars.js_data,
                                                   default=json_default_handler,
                                                   indent="   ")

                result = template_vars.__dict__

                pickled_result = pickle.dumps(result, pickle.HIGHEST_PROTOCOL)
                Redis.set(key, pickled_result)
                Redis.expire(key, 60 * 60)
            rendered_template = render_template("heatmap.html", **result)

        else:
            rendered_template = render_template(
                "empty_collection.html", **{'tool': 'Heatmap'})

    return rendered_template


@app.route("/bnw_page", methods=('POST',))
def bnw_page():
    start_vars = request.form

    traits = [trait.strip() for trait in start_vars['trait_list'].split(',')]
    if traits[0] != "":
        template_vars = send_to_bnw.SendToBNW(request.form)

        result = template_vars.__dict__
        rendered_template = render_template("bnw_page.html", **result)
    else:
        rendered_template = render_template(
            "empty_collection.html", **{'tool': 'BNW'})

    return rendered_template


@app.route("/webgestalt_page", methods=('POST',))
def webgestalt_page():
    start_vars = request.form

    traits = [trait.strip() for trait in start_vars['trait_list'].split(',')]
    if traits[0] != "":
        template_vars = send_to_webgestalt.SendToWebGestalt(request.form)

        result = template_vars.__dict__
        rendered_template = render_template("webgestalt_page.html", **result)
    else:
        rendered_template = render_template(
            "empty_collection.html", **{'tool': 'WebGestalt'})

    return rendered_template


@app.route("/geneweaver_page", methods=('POST',))
def geneweaver_page():
    start_vars = request.form

    traits = [trait.strip() for trait in start_vars['trait_list'].split(',')]
    if traits[0] != "":
        template_vars = send_to_geneweaver.SendToGeneWeaver(request.form)

        result = template_vars.__dict__
        rendered_template = render_template("geneweaver_page.html", **result)
    else:
        rendered_template = render_template(
            "empty_collection.html", **{'tool': 'GeneWeaver'})

    return rendered_template


@app.route("/comparison_bar_chart", methods=('POST',))
def comp_bar_chart_page():
    start_vars = request.form

    traits = [trait.strip() for trait in start_vars['trait_list'].split(',')]
    if traits[0] != "":
        template_vars = comparison_bar_chart.ComparisonBarChart(request.form)
        template_vars.js_data = json.dumps(template_vars.js_data,
                                           default=json_default_handler,
                                           indent="   ")

        result = template_vars.__dict__
        rendered_template = render_template(
            "comparison_bar_chart.html", **result)
    else:
        rendered_template = render_template(
            "empty_collection.html", **{'tool': 'Comparison Bar Chart'})

    return rendered_template


@app.route("/mapping_results_container")
def mapping_results_container_page():
    return render_template("mapping_results_container.html")


@app.route("/loading", methods=('POST',))
def loading_page():
    initial_start_vars = request.form
    start_vars_container = {}
    n_samples = 0  # ZS: So it can be displayed on loading page
    if 'wanted_inputs' in initial_start_vars:
        wanted = initial_start_vars['wanted_inputs'].split(",")
        start_vars = {}
        for key, value in list(initial_start_vars.items()):
            if key in wanted:
                start_vars[key] = value

        sample_vals_dict = json.loads(start_vars['sample_vals'])
        if 'n_samples' in start_vars:
            n_samples = int(start_vars['n_samples'])
        else:
            if 'group' in start_vars:
                dataset = create_dataset(
                    start_vars['dataset'], group_name=start_vars['group'])
            else:
                dataset = create_dataset(start_vars['dataset'])
            start_vars['trait_name'] = start_vars['trait_id']
            if dataset.type == "Publish":
                start_vars['trait_name'] = dataset.group.code + \
                    "_" + start_vars['trait_name']
            samples = dataset.group.samplelist
            if 'genofile' in start_vars:
                if start_vars['genofile'] != "":
                    genofile_string = start_vars['genofile']
                    dataset.group.genofile = genofile_string.split(":")[0]
                    genofile_samples = run_mapping.get_genofile_samplelist(
                        dataset)
                    if len(genofile_samples) > 1:
                        samples = genofile_samples

            for sample in samples:
                if sample in sample_vals_dict:
                    if sample_vals_dict[sample] != "x":
                        n_samples += 1

        start_vars['n_samples'] = n_samples
        start_vars['vals_hash'] = generate_hash_of_string(
            str(sample_vals_dict))
        if start_vars['dataset'] != "Temp":  # Currently can't get diff for temp traits
            start_vars['vals_diff'] = get_diff_of_vals(sample_vals_dict, str(
                start_vars['trait_id'] + ":" + str(start_vars['dataset'])))

        start_vars['wanted_inputs'] = initial_start_vars['wanted_inputs']

        start_vars_container['start_vars'] = start_vars
    else:
        start_vars_container['start_vars'] = initial_start_vars

    rendered_template = render_template("loading.html", **start_vars_container)

    return rendered_template


@app.route("/run_mapping", methods=('POST',))
def mapping_results_page():
    initial_start_vars = request.form
    temp_uuid = initial_start_vars['temp_uuid']
    wanted = (
        'trait_id',
        'dataset',
        'group',
        'species',
        'samples',
        'vals',
        'sample_vals',
        'vals_hash',
        'first_run',
        'output_files',
        'geno_db_exists',
        'method',
        'mapping_results_path',
        'trimmed_markers',
        'selected_chr',
        'chromosomes',
        'mapping_scale',
        'plotScale',
        'score_type',
        'suggestive',
        'significant',
        'num_perm',
        'permCheck',
        'perm_strata',
        'categorical_vars',
        'perm_output',
        'num_bootstrap',
        'bootCheck',
        'bootstrap_results',
        'LRSCheck',
        'covariates',
        'maf',
        'use_loco',
        'manhattan_plot',
        'color_scheme',
        'manhattan_single_color',
        'control_marker',
        'do_control',
        'genofile',
        'genofile_string',
        'pair_scan',
        'startMb',
        'endMb',
        'graphWidth',
        'lrsMax',
        'additiveCheck',
        'showSNP',
        'showGenes',
        'viewLegend',
        'haplotypeAnalystCheck',
        'mapmethod_rqtl',
        'mapmodel_rqtl',
        'temp_trait',
        'n_samples',
        'transform'
    )
    start_vars = {}
    for key, value in list(initial_start_vars.items()):
        if key in wanted:
            start_vars[key] = value

    version = "v3"
    key = "mapping_results:{}:".format(
        version) + json.dumps(start_vars, sort_keys=True)
    result = None  # Just for testing

    if result:
        result = pickle.loads(result)
    else:
        try:
            template_vars = run_mapping.RunMapping(start_vars, temp_uuid)
            if template_vars.no_results:
                raise NoMappingResultsError(
                    start_vars["trait_id"], start_vars["dataset"], start_vars["method"])
        except Exception as exc:
            rendered_template = render_template(
                "mapping_error.html", error=exc, error_type=type(exc).__name__)
            return rendered_template

        if not template_vars.pair_scan:
            template_vars.js_data = json.dumps(template_vars.js_data,
                                               default=json_default_handler,
                                               indent="   ")

        result = template_vars.__dict__

        if result['pair_scan']:
            rendered_template = render_template(
                "pair_scan_results.html", **result)
        else:
            gn1_template_vars = display_mapping_results.DisplayMappingResults(
                result).__dict__

            rendered_template = render_template(
                "mapping_results.html", **gn1_template_vars)

    return rendered_template


@app.route("/export_mapping_results", methods=('POST',))
def export_mapping_results():
    file_path = request.form.get("results_path")
    results_csv = open(file_path, "r").read()
    response = Response(results_csv,
                        mimetype='text/csv',
                        headers={"Content-Disposition": "attachment;filename=" + os.path.basename(file_path)})

    return response


@app.route("/export_corr_matrix", methods=('POST',))
def export_corr_matrix():
    file_path = request.form.get("export_filepath")
    file_name = request.form.get("export_filename")
    results_csv = open(file_path, "r").read()
    response = Response(results_csv,
                        mimetype='text/csv',
                        headers={"Content-Disposition": "attachment;filename=" + file_name + ".csv"})

    return response


@app.route("/export", methods=('POST',))
def export():
    svg_xml = request.form.get("data", "Invalid data")
    filename = request.form.get("filename", "manhattan_plot_snp")
    response = Response(svg_xml, mimetype="image/svg+xml")
    response.headers["Content-Disposition"] = "attachment; filename=%s" % filename
    return response


@app.route("/export_pdf", methods=('POST',))
def export_pdf():
    import cairosvg
    svg_xml = request.form.get("data", "Invalid data")
    filename = request.form.get("filename", "interval_map_pdf")
    pdf_file = cairosvg.svg2pdf(bytestring=svg_xml)
    response = Response(pdf_file, mimetype="application/pdf")
    response.headers["Content-Disposition"] = "attachment; filename=%s" % filename
    return response


@app.route("/network_graph", methods=('POST',))
def network_graph_page():
    start_vars = request.form
    traits = [trait.strip() for trait in start_vars['trait_list'].split(',')]
    if traits[0] != "":
        template_vars = network_graph.NetworkGraph(start_vars)
        template_vars.js_data = json.dumps(template_vars.js_data,
                                           default=json_default_handler,
                                           indent="   ")

        return render_template("network_graph.html", **template_vars.__dict__)
    else:
        return render_template("empty_collection.html", **{'tool': 'Network Graph'})

def __handle_correlation_error__(exc):
    return render_template(
        "correlation_error_page.html",
        error = {
            "error-type": {
                "WrongCorrelationType": "Wrong Correlation Type"
            }[type(exc).__name__],
            "error-message": exc.args[0]
        })

@app.route("/corr_compute", methods=('POST',))
def corr_compute_page():
    import subprocess
    from gn3.settings import CORRELATION_COMMAND
    try:
        correlation_results = compute_correlation(
            request.form, compute_all=True)
    except WrongCorrelationType as exc:
        return __handle_correlation_error__(exc)
    except subprocess.CalledProcessError as cpe:
        actual_command = (
            os.readlink(CORRELATION_COMMAND)
            if os.path.islink(CORRELATION_COMMAND)
            else CORRELATION_COMMAND)
        raise Exception(command_list, actual_command, cpe.stdout) from cpe

    correlation_results = set_template_vars(request.form, correlation_results)
    return render_template("correlation_page.html", **correlation_results)


@app.route("/test_corr_compute", methods=["POST"])
def test_corr_compute_page():

    start_vars = request.form

    try:
        correlation_results = compute_correlation_rust(
            start_vars,
            start_vars["corr_type"],
            start_vars['corr_sample_method'],
            int(start_vars.get("corr_return_results", 500)),
            True)
    except WrongCorrelationType as exc:
        return __handle_correlation_error__(exc)

    correlation_results = set_template_vars(request.form, correlation_results)
    return render_template("correlation_page.html", **correlation_results)


@app.route("/corr_matrix", methods=('POST',))
def corr_matrix_page():
    start_vars = request.form
    traits = [trait.strip() for trait in start_vars['trait_list'].split(',')]
    if len(traits) > 1:
        template_vars = show_corr_matrix.CorrelationMatrix(start_vars)
        template_vars.js_data = json.dumps(template_vars.js_data,
                                           default=json_default_handler,
                                           indent="   ")

        return render_template("correlation_matrix.html", **template_vars.__dict__)
    else:
        return render_template("empty_collection.html", **{'tool': 'Correlation Matrix'})


@app.route("/corr_scatter_plot")
def corr_scatter_plot_page():
    template_vars = corr_scatter_plot.CorrScatterPlot(request.args)
    template_vars.js_data = json.dumps(template_vars.js_data,
                                       default=json_default_handler,
                                       indent="   ")
    return render_template("corr_scatterplot.html", **template_vars.__dict__)


@app.route("/snp_browser", methods=('GET',))
def snp_browser_page():
    with database_connection() as conn, conn.cursor() as cursor:
        template_vars = snp_browser.SnpBrowser(cursor, request.args)
        return render_template("snp_browser.html", **template_vars.__dict__)


@app.route("/db_info", methods=('GET',))
def db_info_page():
    template_vars = InfoPage(request.args)

    return render_template("info_page.html", **template_vars.__dict__)


@app.route("/snp_browser_table", methods=('GET',))
def snp_browser_table():
    with database_connection() as conn, conn.cursor() as cursor:
        snp_table_data = snp_browser.SnpBrowser(cursor, request.args)
        current_page = server_side.ServerSideTable(
            snp_table_data.rows_count,
            snp_table_data.table_rows,
            snp_table_data.header_data_names,
            request.args,
        ).get_page()

        return flask.jsonify(current_page)


@app.route("/tutorial/WebQTLTour", methods=('GET',))
def tutorial_page():
    # ZS: Currently just links to GN1
    return redirect("http://gn1.genenetwork.org/tutorial/WebQTLTour/")


@app.route("/tutorial/security", methods=('GET',))
def security_tutorial_page():
    # ZS: Currently just links to GN1
    return render_template("admin/security_help.html")


@app.route("/submit_bnw", methods=('POST',))
def submit_bnw():
    return render_template("empty_collection.html", **{'tool': 'Correlation Matrix'})

# Take this out or secure it before putting into production


@app.route("/get_temp_data")
def get_temp_data():
    temp_uuid = request.args['key']
    return flask.jsonify(temp_data.TempData(temp_uuid).get_all())


@app.route("/browser_input", methods=('GET',))
def browser_inputs():
    """  Returns JSON from tmp directory for the purescript genome browser"""

    filename = request.args['filename']

    with open("{}/gn2/".format(TEMPDIR) + filename + ".json", "r") as the_file:
        file_contents = json.load(the_file)

    return flask.jsonify(file_contents)


def json_default_handler(obj):
    """Based on http://stackoverflow.com/a/2680060/1175849"""
    # Handle datestamps
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    # Handle integer keys for dictionaries
    elif isinstance(obj, int) or isinstance(obj, uuid.UUID):
        return str(obj)
    # Handle custom objects
    if hasattr(obj, '__dict__'):
        return obj.__dict__
    else:
        raise TypeError('Object of type %s with value of %s is not JSON serializable' % (
            type(obj), repr(obj)))


@app.route("/admin/data-sample/diffs/")
@edit_access_required
def display_diffs_admin():
    TMPDIR = current_app.config.get("TMPDIR")
    DIFF_DIR = f"{TMPDIR}/sample-data/diffs"
    files = []
    if os.path.exists(DIFF_DIR):
        files = os.listdir(DIFF_DIR)
        files = filter(lambda x: not(x.endswith((".approved", ".rejected"))),
                       files)
    return render_template("display_files_admin.html",
                           files=files)


@app.route("/user/data-sample/diffs/")
def display_diffs_users():
    TMPDIR = current_app.config.get("TMPDIR")
    DIFF_DIR = f"{TMPDIR}/sample-data/diffs"
    files = []
    author = g.user_session.record.get(b'user_name').decode("utf-8")
    if os.path.exists(DIFF_DIR):
        files = os.listdir(DIFF_DIR)
        files = filter(lambda x: not(x.endswith((".approved", ".rejected")))
                       and author in x,
                       files)
    return render_template("display_files_user.html",
                           files=files)
