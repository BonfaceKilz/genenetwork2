// Generated by CoffeeScript 1.9.2
(function() {
  var get_z_scores, redraw_prob_plot, root;

  root = typeof exports !== "undefined" && exports !== null ? exports : this;

  get_z_scores = function(n) {
    var i, j, osm_uniform, ref, x;
    osm_uniform = new Array(n);
    osm_uniform[n - 1] = Math.pow(0.5, 1.0 / n);
    osm_uniform[0] = 1 - osm_uniform[n - 1];
    for (i = j = 1, ref = n - 2; 1 <= ref ? j <= ref : j >= ref; i = 1 <= ref ? ++j : --j) {
      osm_uniform[i] = (i + 1 - 0.3175) / (n + 0.365);
    }
    return (function() {
      var k, len, results;
      results = [];
      for (k = 0, len = osm_uniform.length; k < len; k++) {
        x = osm_uniform[k];
        results.push(jStat.normal.inv(x, 0, 1));
      }
      return results;
    })();
  };

  redraw_prob_plot = function(samples, sample_group) {
    var container, h, margin, totalh, totalw, w;
    h = 370;
    w = 600;
    margin = {
      left: 60,
      top: 40,
      right: 40,
      bottom: 40,
      inner: 5
    };
    totalh = h + margin.top + margin.bottom;
    totalw = w + margin.left + margin.right;
    container = $("#prob_plot_container");
    container.width(totalw);
    container.height(totalh);
    var W, all_samples, chart, data, intercept, make_data, names, pvalue, pvalue_str, slope, sorted_names, sorted_values, sw_result, test_str, x, z_scores;
    all_samples = samples[sample_group];
    names = (function() {
      var j, len, ref, results;
      ref = _.keys(all_samples);
      results = [];
      for (j = 0, len = ref.length; j < len; j++) {
        x = ref[j];
        if (all_samples[x] !== null) {
          results.push(x);
        }
      }
      return results;
    })();
    sorted_names = names.sort(function(x, y) {
      return all_samples[x].value - all_samples[y].value;
    });
    max_decimals = 0
    sorted_values = (function() {
      var j, len, results;
      results = [];
      for (j = 0, len = sorted_names.length; j < len; j++) {
        x = sorted_names[j];
        results.push(all_samples[x].value);
        if (all_samples[x].value.countDecimals() > max_decimals) {
            max_decimals = all_samples[x].value.countDecimals()-1
        }
      }
      return results;
    })();
    //ZS: 0.1 indicates buffer, increase to increase buffer
    y_domain = [sorted_values[0] - (sorted_values.slice(-1)[0] - sorted_values[0])*0.1, sorted_values.slice(-1)[0] + (sorted_values.slice(-1)[0] - sorted_values[0])*0.1]
    //sw_result = ShapiroWilkW(sorted_values);
    //W = sw_result.w.toFixed(3);
    //pvalue = sw_result.p.toFixed(3);
    //pvalue_str = pvalue > 0.05 ? pvalue.toString() : "<span style='color:red'>" + pvalue + "</span>";
    //test_str = "Shapiro-Wilk test statistic is " + W + " (p = " + pvalue_str + ")";
    z_scores = get_z_scores(sorted_values.length);
    //ZS: 0.1 indicates buffer, increase to increase buffer
    x_domain = [z_scores[0] - (z_scores.slice(-1)[0] - z_scores[0])*0.1, z_scores.slice(-1)[0] + (z_scores.slice(-1)[0] - z_scores[0])*0.1]
    slope = jStat.stdev(sorted_values);
    intercept = jStat.mean(sorted_values);
    make_data = function(group_name) {
      var sample, value, z_score;
      return {
        key: js_data.sample_group_types[group_name],
        slope: slope,
        intercept: intercept,
        values: (function() {
          var j, len, ref, ref1, results;
          ref = _.zip(get_z_scores(sorted_values.length), sorted_values, sorted_names);
          results = [];
          for (j = 0, len = ref.length; j < len; j++) {
            ref1 = ref[j], z_score = ref1[0], value = ref1[1], sample = ref1[2];
            if (sample in samples[group_name]) {
              results.push({
                x: z_score,
                y: value,
                name: sample
              });
            }
          }
          return results;
        })()
      };
    };
    data = [make_data('samples_primary'), make_data('samples_other'), make_data('samples_all')];
    x_values = {}
    y_values = {}
    point_names = {}
    for (i = 0; i < 3; i++){
      these_x_values = []
      these_y_values = []
      these_names = []
      for (j = 0; j < data[i].values.length; j++){
        these_x_values.push(data[i].values[j].x)
        these_y_values.push(data[i].values[j].y)
        these_names.push(data[i].values[j].name)
      }
      if (i == 0){
        x_values['samples_primary'] = these_x_values
        y_values['samples_primary'] = these_y_values
        point_names['samples_primary'] = these_names
      } else if (i == 1) {
        x_values['samples_other'] = these_x_values
        y_values['samples_other'] = these_y_values
        point_names['samples_other'] = these_names
      } else {
        x_values['samples_all'] = these_x_values
        y_values['samples_all'] = these_y_values
        point_names['samples_all'] = these_names
      }
    }

    intercept_line = {}

    if (sample_group == "samples_primary"){
        first_x = Math.floor(x_values['samples_primary'][0])
        first_x = first_x - first_x*0.1
        last_x = Math.ceil(x_values['samples_primary'][x_values['samples_primary'].length - 1])
        last_x = last_x + last_x*0.1
        first_value = data[0].intercept + data[0].slope * first_x
        last_value = data[0].intercept + data[0].slope * last_x
        intercept_line['samples_primary'] = [[first_x, last_x], [first_value, last_value]]
    } else if (sample_group == "samples_other") {
        first_x = Math.floor(x_values['samples_other'][0])
        first_x = first_x - first_x*0.1
        last_x = Math.ceil(x_values['samples_other'][x_values['samples_other'].length - 1])
        last_x = last_x + last_x*0.1
        first_value = data[1].intercept + data[1].slope * first_x
        last_value = data[1].intercept + data[1].slope * last_x
        intercept_line['samples_other'] = [[first_x, last_x], [first_value, last_value]]
    } else {
        first_x = Math.floor(x_values['samples_all'][0])
        first_x = first_x - first_x*0.1
        last_x = Math.ceil(x_values['samples_all'][x_values['samples_all'].length - 1])
        first_value = data[2].intercept + data[2].slope * first_x
        last_x = last_x + last_x*0.1
        last_value = data[2].intercept + data[2].slope * last_x
        intercept_line['samples_all'] = [[first_x, last_x], [first_value, last_value]]
    }

    var layout = {
        title: 'Quantile-Quantile Plot<a href="https://en.wikipedia.org/wiki/Q-Q_plot"><sup>?</sup></a>',
        margin: {
            l: 50,
            r: 30,
            t: 80,
            b: 80
        },
        xaxis: {
            title: "Normal Theoretical Quantiles",
            range: [first_x, last_x],
            zeroline: false,
            visible: true,
            linecolor: 'black',
            linewidth: 1,
        },
        yaxis: {
            title: "Data Quantiles",
            zeroline: false,
            visible: true,
            linecolor: 'black',
            linewidth: 1,
        },
        hovermode: "closest"
    }

    var primary_trace = {
        x: x_values['samples_primary'],
        y: y_values['samples_primary'],
        mode: 'markers',
        type: 'scatter',
        name: 'Samples',
        text: point_names['samples_primary']
    }
    if ("samples_other" in js_data.sample_group_types) {
        var other_trace = {
            x: x_values['samples_other'],
            y: y_values['samples_other'],
            mode: 'markers',
            type: 'scatter',
            name: js_data.sample_group_types['samples_other'],
            text: point_names['samples_other']
        }
    }

    if (sample_group == "samples_primary"){
        var primary_intercept_trace = {
            x: intercept_line['samples_primary'][0],
            y: intercept_line['samples_primary'][1],
            mode: 'lines',
            type: 'scatter',
            name: 'Normal Function',
        }
    } else if (sample_group == "samples_other"){
        var other_intercept_trace = {
            x: intercept_line['samples_other'][0],
            y: intercept_line['samples_other'][1],
            mode: 'lines',
            type: 'scatter',
            name: 'Normal Function',
        }
    } else {
        var all_intercept_trace = {
            x: intercept_line['samples_all'][0],
            y: intercept_line['samples_all'][1],
            mode: 'lines',
            type: 'scatter',
            name: 'Normal Function',
        }
    }

    if (sample_group == "samples_primary"){
        var data = [primary_trace, primary_intercept_trace]
    } else if (sample_group == "samples_other"){
        var data = [other_trace, other_intercept_trace]
    } else {
        var data = [primary_trace, other_trace, all_intercept_trace]
    }

    console.log("TRACE:", data)
    Plotly.newPlot('prob_plot_div', data, layout)
  };

  root.redraw_prob_plot_impl = redraw_prob_plot;

}).call(this);