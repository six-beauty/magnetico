# coding=utf-8

def clear_dirty(dirty_file):
    dirtys = open(dirty_file, 'r').read().split(',')
    dirty_dict = {}
    for dirty in dirtys:
        if not dirty in dirty_dict:
            dirty_dict[dirty] = 1
        else:
            print(dirty)
            dirty_dict[dirty] += 1

    dirty_keys = dirty_dict.keys()
    hfile = open(dirty_file, 'w')
    hfile.write(','.join(dirty_keys))
    hfile.close()

if __name__=='__main__':
    clear_dirty('色情类.txt')
    clear_dirty('政治类.txt')
    clear_dirty('dirty.txt')
