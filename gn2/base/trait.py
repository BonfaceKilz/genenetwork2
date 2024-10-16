import requests
import simplejson as json
from gn2.wqflask import app

import gn2.utility.hmac as hmac
from gn2.base import webqtlConfig
from gn2.base.webqtlCaseData import webqtlCaseData
from gn2.base.data_set import create_dataset
from gn2.utility.authentication_tools import check_resource_availability
from gn2.utility.tools import get_setting, GN2_BASE_URL
from gn2.utility.redis_tools import get_redis_conn, get_resource_id

from flask import g, request, url_for

from gn2.wqflask.database import database_connection


Redis = get_redis_conn()


def create_trait(**kw):
    assert bool(kw.get('dataset')) != bool(
        kw.get('dataset_name')), "Needs dataset ob. or name"

    assert bool(kw.get('name')), "Needs trait name"


    if bool(kw.get('dataset')):
        dataset = kw.get('dataset')


    else:
        if kw.get('dataset_name') != "Temp":


            dataset = create_dataset(kw.get('dataset_name'))
        else:

            dataset = create_dataset(
                    dataset_name="Temp",
                    dataset_type="Temp",
                    group_name= kw.get('name').split("_")[2])


    if dataset.type == 'Publish':
        permissions = check_resource_availability(
            dataset, g.user_session.user_id, kw.get('name'))
    else:
        permissions = check_resource_availability(
            dataset, g.user_session.user_id)


    if permissions['data'] != "no-access":
        
        the_trait = GeneralTrait(**dict(kw,dataset=dataset))
        if the_trait.dataset.type != "Temp":
            the_trait = retrieve_trait_info(
                the_trait,
                the_trait.dataset,
                get_qtl_info=kw.get('get_qtl_info'))
        return the_trait
    else:
        return None


class GeneralTrait:
    """
    Trait class defines a trait in webqtl, can be either Microarray,
    Published phenotype, genotype, or user input trait

    """

    def __init__(self, get_qtl_info=False, get_sample_info=True, **kw):
        # xor assertion
        assert kw.get("dataset"), "Dataset obj is needed as a kwarg"

        # Trait ID, ProbeSet ID, Published ID, etc.
        self.name = kw.get('name')
        self.dataset = kw.get("dataset")
        self.cellid = kw.get('cellid')
        self.identification = kw.get('identification', 'un-named trait')
        self.haveinfo = kw.get('haveinfo', False)
        # Blat sequence, available for ProbeSet
        self.sequence = kw.get('sequence')
        self.data = kw.get('data', {})
        self.view = True

        # Sets defaults
        self.locus = None
        self.lrs = None
        self.pvalue = None
        self.mean = None
        self.additive = None
        self.num_overlap = None
        self.strand_probe = None
        self.symbol = None
        self.abbreviation = None
        self.display_name = self.name

        self.LRS_score_repr = "N/A"
        self.LRS_location_repr = "N/A"
        self.chr = self.mb = self.locus_chr = self.locus_mb = ""

        if kw.get('fullname'):
            name2 = value.split("::")
            if len(name2) == 2:
                self.dataset, self.name = name2
                # self.cellid is set to None above
            elif len(name2) == 3:
                self.dataset, self.name, self.cellid = name2

        # Todo: These two lines are necessary most of the time, but
        # perhaps not all of the time So we could add a simple if
        # statement to short-circuit this if necessary
        if get_sample_info is not False:
            self = retrieve_sample_data(self, self.dataset)

    def export_informative(self, include_variance=0):
        """
        export informative sample
        mostly used in qtl regression

        """
        samples = []
        vals = []
        the_vars = []
        sample_aliases = []
        for sample_name, sample_data in list(self.data.items()):
            if sample_data.value is not None:
                if not include_variance or sample_data.variance is not None:
                    samples.append(sample_name)
                    vals.append(sample_data.value)
                    the_vars.append(sample_data.variance)
                    sample_aliases.append(sample_data.name2)
        return samples, vals, the_vars, sample_aliases

    @property
    def description_fmt(self):
        """Return a text formated description"""
        if self.dataset.type == 'ProbeSet':
            if self.description:
                formatted = self.description
                if self.probe_target_description:
                    formatted += "; " + self.probe_target_description
            else:
                formatted = "Not available"
        elif self.dataset.type == 'Publish':
            if self.confidential:
                formatted = self.pre_publication_description
            else:
                formatted = self.post_publication_description
        else:
            formatted = "Not available"
        if isinstance(formatted, bytes):
            formatted = formatted.decode("utf-8")
        return formatted

    @property
    def alias_fmt(self):
        """Return a text formatted alias"""

        alias = 'Not available'
        if getattr(self, "alias", None):
            alias = self.alias.replace(";", " ")
            alias = ", ".join(alias.split())

        return alias

    @property
    def wikidata_alias_fmt(self):
        """Return a text formatted alias"""

        alias = 'Not available'
        if self.symbol:
            human_response = requests.get(
                GN2_BASE_URL + "gn3/gene/aliases/" + self.symbol.upper())
            mouse_response = requests.get(
                GN2_BASE_URL + "gn3/gene/aliases/" + self.symbol.capitalize())
            other_response = requests.get(
                GN2_BASE_URL + "gn3/gene/aliases/" + self.symbol.lower())

            if human_response and mouse_response and other_response:
                alias_list = json.loads(human_response.content) + json.loads(
                    mouse_response.content) + \
                    json.loads(other_response.content)

                filtered_aliases = []
                seen = set()
                for item in alias_list:
                    if item in seen:
                        continue
                    else:
                        filtered_aliases.append(item)
                        seen.add(item)
                alias = "; ".join(filtered_aliases)

        return alias

    @property
    def location_fmt(self):
        """Return a text formatted location

        While we're at it we set self.location in case we need it
        later (do we?)

        """

        if self.chr == "Un":
            return 'Not available'

        if self.chr and self.mb:
            self.location = 'Chr %s @ %s Mb' % (self.chr, self.mb)
        elif self.chr:
            self.location = 'Chr %s @ Unknown position' % (self.chr)
        else:
            self.location = 'Not available'

        fmt = self.location
        # XZ: deal with direction
        if self.strand_probe == '+':
            fmt += (' on the plus strand ')
        elif self.strand_probe == '-':
            fmt += (' on the minus strand ')

        return fmt


def retrieve_sample_data(trait, dataset, samplelist=None):
    if samplelist is None:
        samplelist = []

    if dataset.type == "Temp":
        results = Redis.get(trait.name).split()
    else:
        results = dataset.retrieve_sample_data(trait.name)
    # Todo: is this necessary? If not remove
    trait.data.clear()

    if results:
        if dataset.type == "Temp":
            all_samples_ordered = dataset.group.all_samples_ordered()
            for i, item in enumerate(results):
                try:
                    trait.data[all_samples_ordered[i]] = webqtlCaseData(
                        all_samples_ordered[i], float(item))
                except:
                    pass
        else:
            for item in results:
                name, value, variance, num_cases, name2 = item
                if not samplelist or (samplelist and name in samplelist):
                    # name, value, variance, num_cases)
                    trait.data[name] = webqtlCaseData(*item)
    return trait


@app.route("/trait/get_sample_data")
def get_sample_data():
    params = request.args
    trait = params['trait']
    dataset = params['dataset']

    trait_ob = create_trait(name=trait, dataset_name=dataset)
    if trait_ob:
        trait_dict = {}
        trait_dict['name'] = trait
        trait_dict['db'] = dataset
        trait_dict['type'] = trait_ob.dataset.type
        trait_dict['group'] = trait_ob.dataset.group.name
        trait_dict['tissue'] = trait_ob.dataset.tissue
        trait_dict['species'] = trait_ob.dataset.group.species
        trait_dict['url'] = url_for(
            'show_trait_page', trait_id=trait, dataset=dataset)
        if trait_ob.dataset.type == "ProbeSet":
            trait_dict['symbol'] = trait_ob.symbol
            trait_dict['location'] = trait_ob.location_repr
            trait_dict['description'] = trait_ob.description_display
        elif trait_ob.dataset.type == "Publish":
            trait_dict['description'] = trait_ob.description_display
            if trait_ob.pubmed_id:
                trait_dict['pubmed_link'] = trait_ob.pubmed_link
            trait_dict['pubmed_text'] = trait_ob.pubmed_text
        else:
            trait_dict['location'] = trait_ob.location_repr

        return json.dumps([trait_dict, {key: value.value for
                                        key, value in list(
                                            trait_ob.data.items())}])
    else:
        return None


def jsonable(trait, dataset=None):
    """Return a dict suitable for using as json

    Actual turning into json doesn't happen here though"""

    if not dataset:
        dataset = create_dataset(dataset_name=trait.dataset.name,
                                dataset_type=trait.dataset.type,
                                group_name=trait.dataset.group.name)


    trait_symbol = "N/A"
    trait_mean = "N/A"
    if trait.symbol:
        trait_symbol = trait.symbol
    if trait.mean:
        trait_mean = trait.mean

    if dataset.type == "ProbeSet":
        return dict(name=trait.name,
                    display_name=trait.display_name,
                    hmac=hmac.data_hmac('{}:{}'.format(trait.display_name, dataset.name)),
                    view=str(trait.view),
                    symbol=trait_symbol,
                    dataset=dataset.name,
                    dataset_name=dataset.shortname,
                    description=trait.description_display,
                    mean=trait_mean,
                    location=trait.location_repr,
                    chr=trait.chr,
                    mb=trait.mb,
                    lrs_score=trait.LRS_score_repr,
                    lrs_location=trait.LRS_location_repr,
                    lrs_chr=trait.locus_chr,
                    lrs_mb=trait.locus_mb,
                    additive=trait.additive
                    )
    elif dataset.type == "Publish":
        if trait.pubmed_id:
            return dict(name=trait.name,
                        display_name=trait.display_name,
                        hmac=hmac.data_hmac('{}:{}'.format(trait.name, dataset.name)),
                        view=str(trait.view),
                        symbol=trait.abbreviation,
                        dataset=dataset.name,
                        dataset_name=dataset.shortname,
                        description=trait.description_display,
                        abbreviation=trait.abbreviation,
                        authors=trait.authors,
                        pubmed_id=trait.pubmed_id,
                        pubmed_text=trait.pubmed_text,
                        pubmed_link=trait.pubmed_link,
                        mean=trait_mean,
                        lrs_score=trait.LRS_score_repr,
                        lrs_location=trait.LRS_location_repr,
                        lrs_chr=trait.locus_chr,
                        lrs_mb=trait.locus_mb,
                        additive=trait.additive
                        )
        else:
            return dict(name=trait.name,
                        display_name=trait.display_name,
                        hmac=hmac.data_hmac('{}:{}'.format(trait.name, dataset.name)),
                        view=str(trait.view),
                        symbol=trait.abbreviation,
                        dataset=dataset.name,
                        dataset_name=dataset.shortname,
                        description=trait.description_display,
                        abbreviation=trait.abbreviation,
                        authors=trait.authors,
                        pubmed_text=trait.pubmed_text,
                        mean=trait_mean,
                        lrs_score=trait.LRS_score_repr,
                        lrs_location=trait.LRS_location_repr,
                        lrs_chr=trait.locus_chr,
                        lrs_mb=trait.locus_mb,
                        additive=trait.additive
                        )
    elif dataset.type == "Geno":
        return dict(name=trait.name,
                    display_name=trait.display_name,
                    hmac=hmac.data_hmac('{}:{}'.format(trait.display_name, dataset.name)),
                    view=str(trait.view),
                    dataset=dataset.name,
                    dataset_name=dataset.shortname,
                    location=trait.location_repr,
                    chr=trait.chr,
                    mb=trait.mb
                    )
    elif dataset.name == "Temp":
        return dict(name=trait.name,
                    display_name=trait.display_name,
                    hmac=hmac.data_hmac('{}:{}'.format(trait.display_name, dataset.name)),
                    view=str(trait.view),
                    dataset="Temp",
                    dataset_name="Temp")
    else:
        return dict()


def retrieve_trait_info(trait, dataset, get_qtl_info=False):
    if not dataset:
        raise ValueError("Dataset doesn't exist")

    with database_connection(get_setting("SQL_URI")) as conn, conn.cursor() as cursor:
        trait_info = ()
        if dataset.type == 'Publish':
            cursor.execute(
                "SELECT PublishXRef.Id, InbredSet.InbredSetCode, "
                "Publication.PubMed_ID, "
                "CAST(Phenotype.Pre_publication_description AS BINARY), "
                "CAST(Phenotype.Post_publication_description AS BINARY), "
                "CAST(Phenotype.Original_description AS BINARY), "
                "CAST(Phenotype.Pre_publication_abbreviation AS BINARY), "
                "CAST(Phenotype.Post_publication_abbreviation AS BINARY), "
                "PublishXRef.mean, Phenotype.Lab_code, "
                "Phenotype.Submitter, Phenotype.Owner, "
                "Phenotype.Authorized_Users, "
                "CAST(Publication.Authors AS BINARY), "
                "CAST(Publication.Title AS BINARY), "
                "CAST(Publication.Abstract AS BINARY), "
                "CAST(Publication.Journal AS BINARY), "
                "Publication.Volume, Publication.Pages, "
                "Publication.Month, Publication.Year, "
                "PublishXRef.Sequence, Phenotype.Units, "
                "PublishXRef.comments FROM PublishXRef, Publication, "
                "Phenotype, PublishFreeze, InbredSet WHERE "
                "PublishXRef.Id = %s AND "
                "Phenotype.Id = PublishXRef.PhenotypeId "
                "AND Publication.Id = PublishXRef.PublicationId "
                "AND PublishXRef.InbredSetId = PublishFreeze.InbredSetId "
                "AND PublishXRef.InbredSetId = InbredSet.Id AND "
                "PublishFreeze.Id = %s",
                (trait.name, dataset.id,)
            )
            trait_info = cursor.fetchone()

        # XZ, 05/08/2009: Xiaodong add this block to use ProbeSet.Id to find the probeset instead of just using ProbeSet.Name
        # XZ, 05/08/2009: to avoid the problem of same probeset name from different platforms.
        elif dataset.type == 'ProbeSet':
            display_fields_string = ', ProbeSet.'.join(dataset.display_fields)
            display_fields_string = f'ProbeSet.{display_fields_string}'
            cursor.execute(
                f"SELECT {display_fields_string} FROM ProbeSet, ProbeSetFreeze, "
                "ProbeSetXRef WHERE "
                "ProbeSetXRef.ProbeSetFreezeId = ProbeSetFreeze.Id "
                "AND ProbeSetXRef.ProbeSetId = ProbeSet.Id AND "
                "ProbeSetFreeze.Name = %s AND "
                "ProbeSet.Name = %s",
                (dataset.name, str(trait.name),)
            )
            trait_info = cursor.fetchone()
        # XZ, 05/08/2009: We also should use Geno.Id to find marker instead of just using Geno.Name
        # to avoid the problem of same marker name from different species.
        elif dataset.type == 'Geno':
            display_fields_string = ',Geno.'.join(dataset.display_fields)
            display_fields_string = f'Geno.{display_fields_string}'
            cursor.execute(
                f"SELECT {display_fields_string} FROM Geno, GenoFreeze, "
                "GenoXRef WHERE "
                "GenoXRef.GenoFreezeId = GenoFreeze.Id "
                "AND GenoXRef.GenoId = Geno.Id "
                "AND GenoFreeze.Name = %s "
                "AND Geno.Name = %s",
                (dataset.name, trait.name)
            )
            trait_info = cursor.fetchone()
        else:  # Temp type
            cursor.execute(
                f"SELECT {','.join(dataset.display_fields)} "
                f"FROM {dataset.type} WHERE Name = %s",
                (trait.name,)
            )
            trait_info = cursor.fetchone()

        if trait_info:
            trait.haveinfo = True
            for i, field in enumerate(dataset.display_fields):
                holder = trait_info[i]
                if isinstance(holder, bytes):
                    holder = holder.decode("utf-8", errors="ignore")
                setattr(trait, field, holder)

            if dataset.type == 'Publish':
                if trait.group_code:
                    trait.display_name = trait.group_code + "_" + str(trait.name)

                trait.confidential = 0
                if trait.pre_publication_description and not trait.pubmed_id:
                    trait.confidential = 1

                description = trait.post_publication_description

                # If the dataset is confidential and the user has access to confidential
                # phenotype traits, then display the pre-publication description instead
                # of the post-publication description
                trait.description_display = "N/A"
                trait.abbreviation = "N/A"
                if not trait.pubmed_id:
                    if trait.pre_publication_abbreviation:
                        trait.abbreviation = trait.pre_publication_abbreviation
                    if trait.pre_publication_description:
                        trait.description_display = trait.pre_publication_description
                else:
                    if trait.post_publication_abbreviation:
                        trait.abbreviation = trait.post_publication_abbreviation
                    if description:
                        trait.description_display = description.strip()

                if not trait.year.isdigit():
                    trait.pubmed_text = "N/A"
                else:
                    trait.pubmed_text = trait.year

                if trait.pubmed_id:
                    trait.pubmed_link = webqtlConfig.PUBMEDLINK_URL % trait.pubmed_id

            if dataset.type == 'ProbeSet' and dataset.group:
                description_string = trait.description
                target_string = trait.probe_target_description

                if str(description_string or "") != "" and description_string != 'None':
                    description_display = description_string
                else:
                    description_display = trait.symbol

                if (str(description_display or "") != ""
                    and description_display != 'N/A'
                        and str(target_string or "") != "" and target_string != 'None'):
                    description_display = description_display + '; ' + target_string.strip()

                # Save it for the jinja2 template
                trait.description_display = description_display

                trait.location_repr = 'N/A'
                if trait.chr and trait.mb:
                    trait.location_repr = 'Chr%s: %.6f' % (
                        trait.chr, float(trait.mb))

            elif dataset.type == "Geno":
                trait.location_repr = 'N/A'
                if trait.chr and trait.mb:
                    trait.location_repr = 'Chr%s: %.6f' % (
                        trait.chr, float(trait.mb))

            if get_qtl_info:
                # LRS and its location
                trait.LRS_score_repr = "N/A"
                trait.LRS_location_repr = "N/A"
                trait.locus = trait.locus_chr = trait.locus_mb = trait.lrs = trait.pvalue = trait.additive = ""
                if dataset.type == 'ProbeSet' and not trait.cellid:
                    trait.mean = ""
                    cursor.execute(
                        "SELECT ProbeSetXRef.Locus, ProbeSetXRef.LRS, "
                        "ProbeSetXRef.pValue, ProbeSetXRef.mean, "
                        "ProbeSetXRef.additive FROM ProbeSetXRef, "
                        "ProbeSet WHERE "
                        "ProbeSetXRef.ProbeSetId = ProbeSet.Id "
                        "AND ProbeSet.Name = %s AND "
                        "ProbeSetXRef.ProbeSetFreezeId = %s",
                        (trait.name, dataset.id,)
                    )
                    trait_qtl = cursor.fetchone()
                    if any(trait_qtl):
                        trait.locus, trait.lrs, trait.pvalue, trait.mean, trait.additive = trait_qtl
                        if trait.locus:
                            cursor.execute(
                                "SELECT Geno.Chr, Geno.Mb FROM "
                                "Geno, Species WHERE "
                                "Species.Name = %s AND "
                                "Geno.Name = %s AND "
                                "Geno.SpeciesId = Species.Id",
                                (dataset.group.species, trait.locus,)
                            )
                            if result := cursor.fetchone() :
                                trait.locus_chr = result[0]
                                trait.locus_mb = result[1]
                            else:
                                trait.locus_chr = trait.locus_mb = ""
                        else:
                            trait.locus = trait.locus_chr = trait.locus_mb = trait.additive = ""

                if dataset.type == 'Publish':
                    cursor.execute(
                        "SELECT PublishXRef.Locus, PublishXRef.LRS, "
                        "PublishXRef.additive FROM "
                        "PublishXRef, PublishFreeze WHERE "
                        "PublishXRef.Id = %s AND "
                        "PublishXRef.InbredSetId = PublishFreeze.InbredSetId "
                        "AND PublishFreeze.Id = %s", (trait.name, dataset.id,)
                    )
                    if trait_qtl := cursor.fetchone():
                        trait.locus, trait.lrs, trait.additive = trait_qtl
                        if trait.locus:
                            cursor.execute(
                                "SELECT Geno.Chr, Geno.Mb FROM Geno, "
                                "Species WHERE Species.Name = %s "
                                "AND Geno.Name = %s AND "
                                "Geno.SpeciesId = Species.Id",
                                (dataset.group.species, trait.locus,)
                            )
                            if result := cursor.fetchone():
                                trait.locus_chr = result[0]
                                trait.locus_mb = result[1]
                            else:
                                trait.locus = trait.locus_chr = trait.locus_mb = trait.additive = ""
                        else:
                            trait.locus = trait.locus_chr = trait.locus_mb = trait.additive = ""
                    else:
                        trait.locus = trait.lrs = trait.additive = ""
                if (dataset.type == 'Publish' or dataset.type == "ProbeSet"):
                    if str(trait.locus_chr or "") != "" and str(trait.locus_mb or "") != "":
                        trait.LRS_location_repr = LRS_location_repr = 'Chr%s: %.6f' % (
                            trait.locus_chr, float(trait.locus_mb))
                    if str(trait.lrs or "") != "":
                        trait.LRS_score_repr = LRS_score_repr = '%3.1f' % trait.lrs
        else:
            raise KeyError(
                f"{repr(trait.name)} information is not found in the database "
                f"for dataset '{dataset.name}' with id '{dataset.id}'.")
        return trait

def fetch_symbols(trait_db_list):
    """
    Fetch list of trait symbols

    From a list of traits and datasets (where each item has
    the trait and dataset name separated by a colon), return

    """

    trimmed_trait_list = [trait_db for trait_db in trait_db_list
                          if 'Publish' not in trait_db and 'Geno' not in trait_db.split(":")[1]]

    symbol_list = []
    with database_connection(get_setting("SQL_URI")) as conn, conn.cursor() as cursor:
        for trait_db in trimmed_trait_list:
            symbol_query = """
                SELECT ps.Symbol
                FROM ProbeSet as ps
                    INNER JOIN ProbeSetXRef psx ON psx.ProbeSetId = ps.Id
                    INNER JOIN ProbeSetFreeze psf ON psx.ProbeSetFreezeId = psf.Id
                WHERE
                    ps.Name = %(trait_name)s AND
                    psf.Name = %(db_name)s
            """

            cursor.execute(symbol_query, {'trait_name': trait_db.split(":")[0],
                                          'db_name': trait_db.split(":")[1]})
            symbol_list.append(cursor.fetchone()[0])

    return "+".join(symbol_list)