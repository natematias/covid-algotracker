R --no-save <<EOF
output_options = list()
output_options\$includes\$in_header = c('_metatags.html', '_favicon.html')
rmarkdown::render('templates/covid19-dashboard.Rmd', output_file='../index.html', output_options=output_options)
EOF

