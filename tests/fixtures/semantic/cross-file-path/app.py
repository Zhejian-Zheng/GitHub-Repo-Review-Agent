from storage import read_document


def download(request):
    return read_document(request["name"])
