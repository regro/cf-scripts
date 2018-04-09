#!/usr/bin/env xonsh

"""Script for configuring autotick workers based off of a configuration and
jinja2 variables in a template ``.travis.yml``.

This script requires $BOT_ROOT be set to the dir which contains all the
bot worker repos."""
import os
from jinja2 import Environment, FileSystemLoader
from rever.tools import indir

configurations = {'all-feedstock-names': {'doctr_key': 'SmAP2f1JN0n2NM6c4QFipx/6EWnyqPUwPetqeO6EBxVWi5YN5YoJ2B751h5ochLm/rQMT0CmIsjitz31Bue54FnJzJ0rIgLqFz7yjmoeNmpnYk44j+A9XlAhYW6iv4Q6Vd+Fv8nBQICobzNnrxcpCRBL/ExeRKkhzTpqIKoLVWnr0UXUZpZ22e3jKvYgZO8PCnwa2gF/Uifd3TdCSyGvdJtIy/oHRohJNMUo6jlEa51HKIDGPh2SexlMnlol5x8VQTTTaAlBhGT+jjTcBiLss6XAvehC08ge+M7NlGQwYDoaNQRJrHMEIZSLX1hV00kv6bO3kr7O7G2Z93Eur8ypzU18Caqrr7L5/5a+fpZ2hd2DucRlwyHTCKlLmfJuipjSyx8nHPXOjpXb22LUmaExEWBOoiieccc1I433MTZCOAuqV3RimkzV19jAEvvFd4ClVOg4QKKmHHrL9cKD20cRShpbHGKrZT4BNI0jSuEURAILDWP/Kpqy6XjFz8lTSZMZYH8v/wKgZOraop/XAKQVIQ57f02WxPkUQE3x6YVKG+wKd5Nx82J69XZUSurmxcEG+2XlIKQYR4BJyNsylayPvv6p1+V/F298mn90wK0ucsTjhOYgRsCwr4NNVRfYFRah8RXBkSqTEPNsv0DmRLeHLFiGJuOTniNOyE7R3T377K8=',
                                          'script_number': '00',
                                          'repo': '00-find-feedstocks'},
                  'cf-auto-tick': {'doctr_key': 'SiGX99CpSLIHQXcOR8RN3JfL9pdyps1kFISSaaICFOJ65Wp+C5ERWzqZMOr7NlmTijJmCQ4DzGi9h1t+zYWgg+l2XsUXLS+4SDI5SZMCmbP5vHiP2qxnWEiCPTaZrXMNeGcD4yW1KvwxnrRIcyX4JDz2EP4cLKS0laj3kpGTrYPVx2wFrX8/V78SPIZ9S2m1aSOmOtEvyaj1gOdazxGXjLyZ43FbrhwKILweVd8wgsKS4GKsgQIXDRxk4713f32SMOzav+xI6IzHxaoo3RQu3NQQfoeks73/hfxdNyr76fggimXKUPo5tS84W5rU6fwhhZU/ojSxJIMnGcZSRGpmk86nd3l6+jSqU6txinwO5ROL3wvu0o06cY17WAUzPfF/z5Oo5sNbWeuj9Idp9ske4wfWx17q0Z/jkOBiRXYGetjdQTwRlRrqf9R7hja6QGm0giSgXTMGNMyWsI+YIWAZcl5vYBuPCFGc8RUfuRz4zL34oN/4pa7rewkamkNlgTxx9V+lBj46+tNMlrhWhF97z+p+Bpl1zauGxCxCSEGxeWSNyIHgu4z4CKm9q4LG5G201QC71P+6i9Zbo0xcX5PnZi/V1Smky8yQJ4F791GJfSsCMfo98FIQJ7ZoLFyB2YP2dLH538QXL51IKGz8E8PMzZKDpVi+bOzj6iN7e9Qw0LM=',
                                   'script_number': '01',
                                   'repo': 'cf-auto-tick'},
                  'graph-upstream': {'doctr_key': '1ZYymeT9HNKhWGEb6aZ6oxSd2zOYD1L1S0OcWZ8AlWwmOQ7xqBbZR9htT3oA4fl6AoLbFHwaL6v/Y/WfstKOpm9xjUtigFNKsJiAEUp/C/TxeSJen8bvGyT3ja6xxIhJmz7LrwN6ycXPvYoPqXE0gvCAN44IIWRRIaBOa7Q7igeY2u5iSyv4DaFpe0LycdKxvkV9hm9mZKKFOFZ+UCBhiosB76bSXJ49zYucSgn6MUnzpYVTdlvGko85powav0OMXjDs2Lwju+sL9D+5vB49gbeY9jPMv4cVrOSm2CPql7sb7WwlEl3JHxCjLXRgVu1sWRkH/2GGj0Mbu2u6gjxbJ6btGG0p8Q0VROLk+hV9VlVdxFImlsQNL2a+e1MgHZg92ZNM57E8qGASlBG4cRG7qWDi1AQY0e2AiwVJVRtCuc7kYzcFTQ80xqwiuV9cYQDTlKgQdn+esXs+t57yOBYU013ydg6s6JRhu9utnmBjMfvov+NQ37ECohLxPWJaLORJozDWLBLfDr+5PbN4oqzN0V/wKCIg1vXGDKc8L4gH1k/m10BfUwpsyTsXgyupDpIYldyryNU5NKmn5Jq6YqfpBwGDYFeYFUrvDwpwRMPg81zmbJSindKr/oRJ0g3bNFv7nOOd0zxF3HE4WPJADtW1CbweJxpx8LbneC1uvM3FxOQ=',
                                     'script_number': '02',
                                     'repo': 'graph-upstream'},
                  'make-cf-graph': {'doctr_key': 'kUlHJeVjxNf/dt9XSSV+mgHH/9qp30zqABjwdeDe1Nbs5JPVCuLjD7yqL/Pln7jQdzGaTksEIUoFggGSKpXi1SCIZCOlzBax/wAIPTSvJEvUIzFs6Vws7J/mV147tyoNanOHvNw6CvicNhEuWD8HCWUw36kF93yhePwuFvNRWgIof8Ua54d3l2sGTCEHSbIiSvx6eF5WVsIKOWVyjKGu5H3y6HSoOGkFlezw+d9Y2owkx99KPKgDRFRt1BCuKxjhi8Yuv5HTKzCwDuQFC6Ak8uriVTQfMv44Tssl3SP4bDu+1x+zr7mMHTTOHqlYFSOlBtSkDAf6Cctfk903kFQI5TkiDLCSe86tlUiiC2qcFtgL4kll4SMQ5Eu1nmoCjQk457KUb5nkIpWFS5g/TxM8qy0CZF/KHsz2n9M76iDg8V2qS5xyb2hglt51HCGb94tnuR6oBPx+yDzBTGm38c4I8vpzT+8uDEr9bbjh7pO0hzssNCSc/XZld8ctcA5l1M+9Ib/W7QwqK0uelh2VEwpnd8JeMEXGw5jaT+1EA3FUnNTBBOGzJXK3SzG8LAJdQjChSl8vdDvuug2VN04433oZ+PhWv9YrPc+XBs++X/re4pYK7t1dXFBx7qlyMFRWTCYhiPhzgBwbeojuB/MuL6jGld9UqMews+NjdFIyY3j0W6o=',
                                    'script_number': '03',
                                    'repo': 'make-cf-graph'}}

env = Environment(loader=FileSystemLoader(
    [os.path.expanduser('.')]))

for k, ctx in configurations.items():
    d = os.path.join($BOT_ROOT, k)
    output = os.path.join(d, '.travis.yml')
    template = env.get_template('travis_template.yml')
    result = template.render(ctx)
    with indir(d):
        with open(output, 'w') as f:
            f.write(result)
        git fetch --all
        # make sure local is up-to-date with origin
        git checkout master
        git pull origin master or git pull upstream master
        git commit -am "update worker"
        git push git@github.com:@(ctx['repo']).git master
