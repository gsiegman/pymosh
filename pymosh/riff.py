import struct
import os
import sys

list_headers = ('RIFF', 'LIST')

class UnexpectedEOF(Exception):
    pass

class RiffIndexChunk(object):
    def __init__(self, fh, header, length, position):
        self.file = fh
        self.header = header
        self.length = int(length)
        self.position = position

    @staticmethod
    def from_file(fh, position):
        pass

    def __str__(self):
        data = self.data
        return '{header}{length}{data}'.format(header=self.header,
                length=struct.pack('<I', self.length), data=data)

    def __len__(self):
        return self.length

    def __getslice__(self, start, end):
        current = self.file.tell()
        self.file.seek(self.position+start)
        if start < end and start <= self.length:
            if end > self.length:
                end = self.length
            data = self.file.read(end-start)
            self.file.seek(current)
            return data
        else:
            return ''

    def __getitem__(self, index):
        return self[index:index+1]

    def _data(self):
        """Read data from the file."""
        current_position = self.file.tell()
        self.file.seek(self.position)
        data = self.file.read(self.length)
        self.file.seek(current_position)
        if self.length % 2:
            data += '\x00' # Padding byte
        return data
    data = property(_data)

    def as_data(self):
        """Return a RiffDataChunk read from the file."""

class RiffIndexList(RiffIndexChunk):
    def __init__(self, fh, header, length, list_type, position, *args, **kwargs):
        self.file = fh
        self.header = header
        self.type = list_type
        self.length = int(length)
        self.position = position
        if 'chunks' in kwargs:
            self.chunks = kwargs['chunks']
        else:
            self.chunks = []

    def __getitem__(self, index):
        return self.chunks.__getitem__(index)

    def __setitem__(self, index, value):
        return self.chunks.__setitem__(index, value)

    def __delitem__(self, index):
        return self.chunks.__delitem__(index)

    def __iter__(self):
        return self.chunks.__iter__()

    def next(self):
        return self.chunks.next()

    def __len__(self):
        return self.chunks.__len__()

    def chunk_length(self):
        length = 0
        for chunk in self.chunks:
            length += chunk.length + 8 # Header and length bytes
            length += chunk.length % 2 # Pad byte
        return length

    def __str__(self):
        length = self.chunk_length() + len(self.type)
        return '{header}{length}{list_type}'.format(header=self.header,
                length=struct.pack('<I', length), list_type=self.type)

    def find(self, header, list_type=None):
        """Find the first chunk with specified header and optional list type."""
        for chunk in self:
            if chunk.header == header and (not list_type or (header in
                    list_headers and chunk.type == list_type)):
                return chunk
            elif chunk.header in list_headers:
                result = chunk.find(header, list_type)
                if result:
                    return result
        return None

    def find_all(self, header, list_type=None):
        """Find all direct children with header and optional list type."""
        found = []
        for chunk in self:
            if chunk.header == header and (not list_type or (header in
                list_headers and chunk.type == list_type)):
                found.append(chunk)
        return found

    def replace(self, child, replacement):
        """Replace a child chunk with something else."""
        for i in range(len(self)):
            if self[i] == child:
                self[i] = replacement

    def remove(self, child):
        """Remove a child element."""
        for i in range(len(self)):
            if self[i] == child:
                del self[i]

class RiffDataChunk(object):
    """A RIFF chunk with data in memory instead of a file."""

    def __init__(self, header, data):
        self.header = header
        self.length = len(data)
        self.data = data

    @staticmethod
    def from_data(data):
        """Create a chunk from data including header and length bytes."""
        header, length = struct.unpack('4s<I', data[:8])
        data = data[8:]
        return RiffDataChunk(header, data)

    def __str__(self):
        pad = '\x00' if self.length % 2 else ''
        return '{header}{length}{data}'.format(header=self.header,
                length=struct.pack('<I', self.length), data=self.data, pad=pad)

    def __len__(self):
        return self.length

    def __getslice__(self, start, end):
        return self.data[start:end]

    def __getitem__(self, index):
        return self.data[index]

class RiffIndex(RiffIndexList):
    def __init__(self, filename):
        self.file = open(filename, 'rb')
        self.chunks = []
        self.size = self.get_size()
        self.scan_file()

    def write(self, fh):
        if not isinstance(fh, file):
            fh = open(fh, 'wb')
        def print_chunks(chunks):
            for chunk in chunks:
                fh.write(str(chunk))
                if chunk.header in ('RIFF', 'LIST'):
                    print_chunks(chunk.chunks)
        print_chunks(self.chunks)

    def get_size(self):
        current = self.file.tell()
        self.file.seek(0, 2)
        size = self.file.tell()
        self.file.seek(current)
        return size

    def readlen(self, length):
        buf = self.file.read(length)
        if len(buf) == length:
            return buf
        else:
            raise UnexpectedEOF('End of file reached after {0} bytes.'.format(len(buf)))

    def scan_file(self):
        header = self.readlen(4)
        if header == 'RIFF':
            length, list_type = struct.unpack('<I4s', self.readlen(8))
            chunks = self.scan_chunks(length-4)
            self.chunks.append(RiffIndexList(self.file, header, length, list_type, 0,
                chunks=chunks))
        else:
            raise Exception('Not a RIFF file!')

    def scan_chunks(self, data_length):
        chunks = []
        total_length = 0
        while total_length < data_length:
            header = self.readlen(4)
            total_length += 4

            length, = struct.unpack('<I', self.file.read(4))
            total_length += length + 4 # add 4 for itself

            position = self.file.tell()

            if header in list_headers:
                list_type = self.readlen(4)
                data = self.scan_chunks(length-4)
                if length % 2:
                    # Padding byte
                    self.file.seek(1, os.SEEK_CUR)
                    total_length += 1
                chunks.append(RiffIndexList(self.file, header, length, list_type, position, chunks=data))
            else:
                self.file.seek(length, os.SEEK_CUR)
                if length % 2:
                    # Padding byte
                    self.file.seek(1, os.SEEK_CUR)
                    total_length += 1
                chunks.append(RiffIndexChunk(self.file, header, length, position))
        return chunks
